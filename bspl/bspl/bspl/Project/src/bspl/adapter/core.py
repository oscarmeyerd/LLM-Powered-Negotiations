import asyncio
import aiorun
import logging
import json
import datetime
import sys
import os
import math
import socket
import inspect
import yaml
import agentspeak
import agentspeak.stdlib
import random
import colorama
from types import MethodType
from asyncio.queues import Queue
from .store import Store
from .message import Message
from functools import partial
from .emitter import Emitter
from .receiver import Receiver
from .scheduler import Scheduler, exponential
from .statistics import stats, increment
from .jason import Environment, Agent, Actions, actions
from .event import Event, ObservationEvent, ReceptionEvent, EmissionEvent, InitEvent
from . import policies
from ..protocol import Parameter
import bspl
import bspl.adapter.jason
import bspl.adapter.schema
from bspl.utils import identity

FORMAT = "%(asctime)-15s %(module)s: %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)
logger = logging.getLogger("bspl")

SUPERCRITICAL = logging.CRITICAL + 10  # don't want any logs
logging.getLogger("aiorun").setLevel(SUPERCRITICAL)

COLORS = [
    (colorama.Back.GREEN, colorama.Fore.BLACK),
    (colorama.Back.MAGENTA, colorama.Fore.BLACK),
    (colorama.Back.YELLOW, colorama.Fore.BLACK),
    (colorama.Back.BLUE, colorama.Fore.BLACK),
    (colorama.Back.CYAN, colorama.Fore.BLACK),
    (colorama.Back.RED, colorama.Fore.BLACK),
]


def select_endpoint(agent_endpoints, system_name):
    """
    Select one endpoint from a list of agent endpoints using deterministic hash-based selection.

    This function provides session affinity - the same system will always connect to the same
    endpoint when multiple endpoints are available. This deterministic behavior aids in debugging
    and ensures consistent message routing.

    Args:
        agent_endpoints: Either a single endpoint tuple (host, port) or a list of such tuples
        system_name: Name of the system, used as hash input for deterministic selection

    Returns:
        A single endpoint tuple (host, port)
    """
    if isinstance(agent_endpoints, list):
        if len(agent_endpoints) == 1:
            return agent_endpoints[0]
        # Use hash of system name for deterministic selection
        index = hash(system_name) % len(agent_endpoints)
        return agent_endpoints[index]
    else:
        # Single endpoint (tuple)
        return agent_endpoints


class Adapter:
    def __init__(
        self,
        name,
        systems,
        agents,
        emitter=Emitter(),
        receiver=None,
        color=None,
        in_place=False,
        debug=False,
        **kwargs,
    ):
        """
        Initialize the agent adapter.

        name: name of this agent
        systems: a list of MAS to participate in
        agents: a dictionary mapping agent names to endpoints
        emitter: encodes messages for transmission over the network
        receiver: reads messages from the network and decodes them
        color: distinguish agent by color in console logs
        in_place: detect completed forms instead of using return value
        debug: turn on debug logging when True
        """
        self.name = name

        self.logger = logging.getLogger(f"bspl.adapter.{name}")
        self.logger.propagate = False
        color = color or (
            COLORS[hash(name) % len(COLORS)]
            if name
            else COLORS[random.randint(0, len(COLORS) - 1)]
        )
        self.color = agentspeak.stdlib.COLORS[0] = color
        reset = colorama.Fore.RESET + colorama.Back.RESET
        formatter = logging.Formatter(
            f"%(asctime)-15s ({''.join(self.color)}{name}{reset}): %(message)s"
        )
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.logger.handlers.clear()
        self.logger.addHandler(handler)
        # Check for environment variable to enable debug mode
        env_debug = os.environ.get("BSPL_ADAPTER_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if debug or env_debug:
            logging.getLogger("bspl").setLevel(logging.DEBUG)

        self.roles = {
            r for s in systems.values() for r in s["roles"] if s["roles"][r] == name
        }
        self.protocols = [s["protocol"] for s in systems.values()]
        self.systems = systems
        self.agents = agents
        self.addresses = self.agents[self.name]
        self.reactors = {}  # dict of message -> [handlers]
        self.generators = {}  # dict of (scheema tuples) -> [handlers]
        self.history = Store(systems)
        self.emitter = emitter
        if receiver:
            self.receivers = [receiver]
        else:
            self.receivers = []
            for addr in self.addresses:
                self.receivers.append(Receiver(addr))
        self.schedulers = []
        self.messages = {
            message.qualified_name: message
            for p in self.protocols
            for name, message in p.messages.items()
        }

        for p in self.protocols:
            self.inject(p)

        self.events = Queue()
        self.enabled_messages = Store(systems)
        self.decision_handlers = {}
        self._in_place = in_place
        self.kwargs = kwargs

    def debug(self, msg):
        self.logger.debug(msg)

    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def inject(self, protocol):
        """Install helper methods into schema objects"""

        from bspl.protocol import Message

        Message.__call__ = bspl.adapter.schema.instantiate(self)

        for m in protocol.messages.values():
            m.match = MethodType(bspl.adapter.schema.match, m)
            m.adapter = self

    async def receive(self, data):
        if not isinstance(data, dict):
            self.warning("Data does not parse to a dictionary: {}".format(data))
            return

        schema = self.messages[data["schema"]]
        message = Message(schema, data["payload"], meta=data.get("meta", {}))
        message.meta["received"] = datetime.datetime.now()
        if self.history.is_duplicate(message):
            self.debug("Duplicate message: {}".format(message))
            increment("dups")
            # Don't react to duplicate messages
            # message.duplicate = True
            # await self.react(message)
        elif self.history.check_integrity(message):
            self.debug("Received message: {}".format(message))
            increment("receptions")
            self.history.add(message)
            await self.signal(ReceptionEvent(message))

    async def send(self, *messages):
        def prep(message):
            # Handle multiple recipients by creating copies for each destination
            prepared_messages = []

            if hasattr(message, "_dest") and message._dest:
                # Backwards compatibility: single dest already set
                prepared_messages.append(message)
            else:
                system = self.systems[message.system]
                # Create a copy for each recipient
                for recipient_role in message.schema.recipients:
                    recipient_agent = system["roles"][recipient_role]
                    agent_endpoints = self.agents[recipient_agent]

                    # Handle multiple endpoints per agent using deterministic selection
                    endpoint = select_endpoint(agent_endpoints, message.system)

                    # Create message copy with specific destination
                    msg_copy = Message(
                        message.schema,
                        message.payload.copy(),
                        message.meta.copy(),
                        message.acknowledged,
                        endpoint,
                        message.adapter,
                        message.system,
                    )
                    prepared_messages.append(msg_copy)

            return prepared_messages

        # Flatten the list of message copies from prep
        all_prepared = []
        for m in messages:
            if not self.history.is_duplicate(m):
                prepared = prep(m)
                all_prepared.extend(prepared)
        emissions = set(all_prepared)
        if len(emissions) < len(messages):
            self.info(
                f"Skipped {len(messages) - len(emissions)} duplicate messages: {set(messages).difference(emissions)}"
            )

        if self.history.check_emissions(emissions):
            self.debug(f"Sending {emissions}")
            for m in emissions:
                increment("emissions")
                increment("observations")
                self.history.add(m)
            if len(emissions) > 1 and hasattr(self.emitter, "bulk_send"):
                self.debug(f"bulk sending {len(emissions)} messages")
                await self.emitter.bulk_send(emissions)
            else:
                for m in emissions:
                    await self.emitter.send(m)
            await self.signal(EmissionEvent(emissions))

    def register_reactor(self, schema, handler, index=None):
        if schema in self.reactors:
            rs = self.reactors[schema]
            if handler not in rs:
                rs.insert(index if index is not None else len(rs), handler)
        else:
            self.reactors[schema] = [handler]

    def register_reactors(self, handler, schemas=[]):
        for s in schemas:
            self.register_reactor(s, handler)

    def clear_reactors(self, *schemas):
        for s in schemas:
            self.reactors[s] = []

    def reaction(self, *schemas):
        """
        Decorator for declaring reactor handler.

        Example:
        @adapter.reaction(MessageSchema)
        async def handle_message(message):
            'do stuff'
        """
        return partial(self.register_reactors, schemas=schemas)

    async def react(self, message):
        """
        Handle emission/reception of message by invoking corresponding reactors.
        """
        reactors = self.reactors.get(message.schema)
        if reactors:
            for r in reactors:
                message.adapter = self
                await r(message)

    def enabled(self, *schemas, **options):
        """
        Decorator for declaring enabled message generators.

        Example:
        @adapter.enabled(MessageSchema)
        async def generate_message(msg):
            msg.bind("param", value)
            return msg
        """
        return partial(self.register_generators, schemas=schemas, options=options)

    def register_generators(self, handler, schemas, options={}):
        if schemas in self.generators:
            gs = self.generators[schemas]
            if handler not in gs:
                gs.insert(index if index is not None else len(gs), handler)
        else:
            self.generators[schemas] = [handler]

    async def handle_enabled(self, message):
        """
        Handle newly observed message by checking for newly enabled messages.

        1. Cycle through all registered schema tuples
        2. Check if all messages in tuple are enabled
        3. If so, invoke the handlers in sequence
        4. Continue until a message is returned
        5. Break loop after the first handler returns a message, and send it

        Note: sending a message triggers the loop again
        """
        for tup in self.generators.keys():
            for group in zip(*(schema.match(message) for schema in tup)):
                for handler in self.generators[tup]:
                    partials = [m.partial() for m in group]
                    # assume it returns only one message for now
                    msg = await handler(*partials)
                    if self._in_place:
                        instances = []
                        for m in partials:
                            self.debug(f"Checking {m}")
                            if m.instances:
                                instances.extend(m.instances)
                                m.instances.clear()
                        if instances:
                            self.debug(f"found instances: {instances}")
                            await self.send(*instances)
                            # short circuit on first message(s) to send
                            return
                    elif msg:
                        await self.send(msg)
                        # short circuit on first message to send
                        return

    def decision(
        self, handler=None, event=None, filter=None, received=None, sent=None, **kwargs
    ):
        """
        Decorator for declaring decision handlers.

        Example:
        @adapter.decision
        async def decide(enabled)
            for m in enabled:
                if m.schema is Quote:
                    m.bind("price", 10)
                    return m
        """
        fn = identity
        if event != None:
            if isinstance(event, str):
                prev = fn
                fn = lambda e: (prev(e) and (hasattr(e, "type") and e.type == event))
            elif issubclass(event, Event):
                prev = fn
                fn = lambda e: (prev(e) and isinstance(e, event))
            elif isinstance(event, bspl.protocol.Message):
                schema = event
                prev = fn
                fn = lambda e: (
                    prev(e)
                    and isinstance(e, ObservationEvent)
                    and any(m.schema == event for m in e.messages)
                )
        if received != None:
            schema = received
            prev = fn
            fn = lambda e: (
                prev(e)
                and isinstance(e, ReceptionEvent)
                and any(m.schema == event for m in e.messages)
            )
        if sent != None:
            schema = sent
            prev = fn
            fn = lambda e: (
                prev(e)
                and isinstance(e, EmissionEvent)
                and any(m.schema == event for m in e.messages)
            )
        if filter != None:
            prev = fn
            fn = lambda e: (prev(e) and filter(e))

        if kwargs:

            def match(event):
                for k in kwargs:
                    if k in event:
                        return event[k] == kwargs[k]

            prev = fn
            fn = lambda e: (prev(e) and match(e))

        def register(handler):
            if fn not in self.decision_handlers:
                self.decision_handlers[fn] = {handler}
            else:
                self.decision_handlers[fn].add(handler)

        if handler != None:
            register(handler)
        else:
            return register

    def add_policies(self, *ps, when=None):
        s = None
        if when:
            s = Scheduler(when)
            self.schedulers.append(s)
        for policy in ps:
            policy.install(self, s)

    def load_policies(self, spec):
        if type(spec) is str:
            spec = yaml.full_load(spec)
        if any(r.name in spec for r in self.roles):
            for r in self.roles:
                if r.name in spec:
                    for condition, ps in spec[r.name].items():
                        self.add_policies(*ps, when=condition)
        else:
            # Assume the file contains policies only for agent
            for condition, ps in spec.items():
                self.add_policies(*ps, when=condition)

    def load_policy_file(self, path):
        with open(path) as file:
            spec = yaml.full_load(file)
            self.load_policies(spec)

    def start(self, *tasks, use_uvloop=True):
        if use_uvloop:
            try:
                import uvloop
            except:
                use_uvloop = False

        async def main():
            self.events = Queue()
            loop = asyncio.get_running_loop()
            loop.create_task(self.update_loop())

            for r in self.receivers:
                await r.task(self)

            if hasattr(self.emitter, "task"):
                await self.emitter.task()

            for s in self.schedulers:
                # todo: add stop event support
                loop.create_task(s.task(self))

            await self.signal(InitEvent())

            for t in tasks:
                loop.create_task(t)

        self.running = True
        aiorun.run(main(), stop_on_unhandled_errors=True, use_uvloop=use_uvloop)

    async def stop(self):
        await self.receiver.stop()
        await self.emitter.stop()
        self.running = False

    async def signal(self, event):
        """
        Publish an event for triggering the update loop
        """
        if not hasattr(self, "events"):
            self.events = Queue()
        if isinstance(event, str):
            event = Event(event)
        await self.events.put(event)

    async def update(self):
        event = await self.events.get()
        emissions = await self.process(event)
        if emissions:
            await self.send(*emissions)

    async def update_loop(self):
        while self.running:
            await self.update()

    async def process(self, event):
        """
        Process a single functional step in a decision loop

        (state, observations) -> (state, enabled, event) -> (state, emissions) -> state
        - state :: the local state, history of observed messages + other local information
        - event :: an object representing the new information that triggered the processing loop; could be an observed message or a signal from the agent internals or environment
        - enabled :: a set of all currently enabled messages, indexed by their keys; the enabled set is incrementally constructed and stored in the state
        - emissions :: a list of message instance for sending

        State can be threaded through the entire loop to make it more purely functional, or left implicit (e.g. a property of the adapter) for simplicity
        Events need a specific structure;
        """

        emissions = []

        if isinstance(event, ObservationEvent):
            # Update the enabled messages if there was an emission or reception
            observations = event.messages
            for m in observations:
                self.debug(f"observing: {m}")
                if "trace" in self.kwargs:
                    # if tracing is enabled, log the observation
                    if event.type == "reception":
                        self.info(f"Received: {m}")
                    elif event.type == "emission":
                        self.info(f"Sent: {m}")
                if hasattr(self, "bdi"):
                    self.bdi.observe(m)
                    # wake up bdi logic
                    self.environment.wake_signal.set()
                await self.react(m)
                await self.handle_enabled(m)
            event = self.compute_enabled(observations)
        elif isinstance(event, InitEvent):
            self.construct_initiators()

        for fn in self.decision_handlers:
            if fn(event):
                for d in self.decision_handlers[fn]:
                    s = inspect.signature(d).parameters
                    result = None
                    if len(s) == 1:
                        result = await d(self.enabled_messages)
                    elif len(s) == 2:
                        result = await d(self.enabled_messages, event)

                    if self._in_place:
                        instances = []
                        for m in self.enabled_messages.messages():
                            if m.instances:
                                instances.extend(m.instances)
                                m.instances.clear()
                        emissions.extend(instances)
                    elif result:
                        # Handle both single messages and lists/collections
                        if (
                            hasattr(result, "__iter__")
                            and not isinstance(result, (str, dict))
                            and not hasattr(result, "schema")
                        ):
                            emissions.extend(result)
                        else:
                            emissions.append(result)

        if hasattr(self, "bdi"):
            emissions.extend(
                bspl.adapter.jason.bdi_handler(self.bdi, self.enabled_messages, event)
            )
            self.environment.wake_signal.set()
        return emissions

    def construct_initiators(self):
        # Add initioators
        for sID, s in self.systems.items():
            for m in s["protocol"].initiators():
                if m.sender in self.roles:
                    p = m().partial()
                    p.meta["system"] = sID
                    self.enabled_messages.add(p)

    def compute_enabled(self, observations):
        """
        Compute updates to the enabled set based on a list of an observations
        """
        # clear out matching keys from enabled set
        removed = set()
        for msg in observations:
            context = self.enabled_messages.context(msg)
            removed.update(context.messages())
            context.clear()

        added = set()
        for o in observations:
            for schema in self.systems[o.system]["protocol"].messages.values():
                if schema.sender in self.roles:
                    added.update(schema.match(o))
        for m in added:
            self.debug(f"new enabled message: {m}")
            self.enabled_messages.add(m.partial())
        removed.difference_update(added)

        return {"added": added, "removed": removed, "observations": observations}

    @property
    def environment(self):
        if not hasattr(self, "_env"):
            self._env = Environment()
            # enable asynchronous processing of environment
            self.schedulers.append(self._env)
        return self._env

    def load_asl(self, path, rootdir=None):
        actions = Actions(bspl.adapter.jason.actions)
        with open(path) as source:
            self.bdi = self.environment.build_agent(
                source, actions, agent_cls=bspl.adapter.jason.Agent
            )
            self.bdi.name = self.name or self.bdi.name
            self.bdi.bind(self)
