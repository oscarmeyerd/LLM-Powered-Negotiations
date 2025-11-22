#!/usr/bin/env python3

import agentspeak
import agentspeak.runtime
import agentspeak.ext_stdlib
import asyncio
import uuid
import collections
import logging

from agentspeak import Actions
from agentspeak.runtime import Agent

from .message import Message
from ..utils import upcamel

logger = logging.getLogger("bspl")


class Environment(agentspeak.runtime.Environment):
    async def task(self, adapter):
        """Async alternative to Environment.run() so BDI processing can run alongside protocol adapter"""
        self.adapter = adapter
        self.wake_signal = asyncio.Event()

        # add an outer loop to wake up environment for an external event
        while self.adapter.running:
            await self.loop()
            await self.wake_signal.wait()

    async def loop(self):
        self.wake_signal.clear()
        maybe_more_work = True
        while maybe_more_work:
            maybe_more_work = False
            for agent in self.agents.values():
                if agent.step():
                    maybe_more_work = True

            if not maybe_more_work:
                deadlines = (
                    agent.shortest_deadline() for agent in self.agents.values()
                )
                deadlines = [deadline for deadline in deadlines if deadline is not None]
                if deadlines:
                    await asyncio.sleep(min(deadlines) - self.time())
                    maybe_more_work = True


class Agent(agentspeak.runtime.Agent):
    def bind(self, adapter):
        """For late binding"""
        self.adapter = adapter

    def believe(self, term):
        logger.debug(f"({self.name}) believing: {term}")
        self.call(
            agentspeak.Trigger.addition,
            agentspeak.GoalType.belief,
            term,
            agentspeak.runtime.Intention(),
        )

    def observe(self, message):
        term = message.term()
        self.believe(term)


actions = Actions(agentspeak.ext_stdlib.actions)

actions.add_function(".uuid", (), lambda: str(uuid.uuid4()))


@actions.add(".emit", 1)
def emit(agent, term, intention):
    """
    emit/1 sends a message represented by a single term
    """
    message = agentspeak.evaluate(term.args[0], intention.scope)
    args = [agentspeak.evaluate(p, intention.scope) for p in message.args]
    name = message.functor
    system = args[0]
    sender = args[1]
    recipient = args[2]
    parameters = args[3:]

    # resolve literals to be serializeable
    params = [
        p if not isinstance(p, agentspeak.Literal) else p.asl_repr() for p in parameters
    ]
    # Find schema using name
    schema = agent.adapter.systems[system]["protocol"].find_schema(name=upcamel(name))
    # Construct payload using parameter list
    payload = schema.zip_params(*params)

    m = Message(schema, payload, system=system)

    if isinstance(recipient, str) and ":" in recipient:
        addr, port = recipient.split(":")
        m.dest = (addr, int(port))

    asyncio.create_task(agent.adapter.send(m))
    yield


@actions.add(".emitAll", 1)
def emit(agent, term, intention):
    """
    emitAll/1 sends a message represented by a single term to all systems
    """
    message = agentspeak.evaluate(term.args[0], intention.scope)
    args = [agentspeak.evaluate(p, intention.scope) for p in message.args]
    name = message.functor
    # don't need system
    # system = args[0]
    sender = args[1]
    recipient = args[2]
    parameters = args[3:]

    # resolve literals to be serializeable
    params = [
        p if not isinstance(p, agentspeak.Literal) else p.asl_repr() for p in parameters
    ]

    for system in agent.adapter.systems:
        # Find schema using name
        schema = agent.adapter.systems[system]["protocol"].find_schema(
            name=upcamel(name)
        )
        # Construct payload using parameter list
        payload = schema.zip_params(*params)

        m = Message(schema, payload, system=system)

        if isinstance(recipient, str) and ":" in recipient:
            addr, port = recipient.split(":")
            m.dest = (addr, int(port))

        asyncio.create_task(agent.adapter.send(m))
    yield


def find_plan(agent, term, memo):
    agent.adapter.debug(f"Finding plan for {term}")
    frozen = agentspeak.freeze(term, {}, memo)
    intention = agentspeak.runtime.Intention()

    for plan in agent.plans[
        (
            agentspeak.Trigger.addition,
            agentspeak.GoalType.achievement,
            frozen.functor,
            len(frozen.args),
        )
    ]:
        for _ in agentspeak.unify_annotated(
            plan.head, frozen, intention.scope, intention.stack
        ):
            for _ in plan.context.execute(agent, intention):
                intention.head_term = frozen
                intention.instr = plan.body
                intention.calling_term = term

                # We're only generating one intention, using the first result
                return intention


def add_intention(agent, intention):
    stack = collections.deque()
    stack.append(intention)
    agent.intentions.append(stack)


def bdi_handler(agent, enabled, event):
    memo = {}
    if not isinstance(event, dict):
        logger.debug(event)
        return
    for m in event.get("added", []):
        term = m.term()
        agent.believe(m.enabled_term())
        intention = find_plan(agent, term, memo)
        if intention:
            add_intention(agent, intention)
            agent.run()
            emission = m.resolve(term, intention.scope, memo)
            if emission:
                yield emission
    for m in event.get("removed", []):
        agent.remove_belief(m.enabled_term(), agentspeak.runtime.Intention())
