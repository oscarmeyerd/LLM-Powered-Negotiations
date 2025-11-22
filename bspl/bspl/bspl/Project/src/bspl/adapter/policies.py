import yaml
import tatsu
import os
import logging
import datetime
import uuid

logger = logging.getLogger("bspl")


def autoincrement(parameter):
    def _autoinc(context):
        current = 0
        for m in context.messages():
            current = max(current, m.payload.get(parameter))
        return current + 1

    return _autoinc


def guid():
    return str(uuid.uuid4())


generators = {"autoincrement": autoincrement, "guid": guid}


def map_message(map, kind, m):
    return map[kind][m.schema][0](**m.payload, **{map[kind][m.schema][1]: guid()})


def map_messages(map, kind, messages):
    for m in messages:
        yield map_message(map, kind, m)


grammar_path = os.path.join(os.path.dirname(__file__), "policy.gr")
with open(grammar_path, "r", encoding="utf8") as grammar:
    model = tatsu.compile(grammar.read())


def lookup(protocol, names):
    return [protocol.messages[name] for name in names]


def from_ast(protocol, ast):
    action = ast.get("action")
    cls = {
        "remind": Remind,
        "forward": Forward,
        "send": Send,
    }.get(action["verb"])

    policy = cls(*lookup(protocol, action["messages"]))

    if ast.get("delay"):
        policy.after(float(ast["delay"]))

    if ast.get("prep"):
        if ast["prep"] == "until":
            policy.until
        elif ast["prep"] == "upon":
            policy.upon
        else:
            raise Exception("Unknown preposition: {}".format(ast["prep"]))

    def add_event(event):
        if type(event) is tuple:
            if event[0] == "or":
                policy.Or
            elif event[0] == "and":
                policy.And
            else:
                raise Exception("Unknown conjunction: {}".format(event[0]))

            for e in event[1:]:
                add_event(e)
            return

        kind = event["type"]
        messages = lookup(protocol, event["messages"])
        if kind == "received":
            policy.received(*messages)

    if ast.get("events"):
        add_event(ast["events"])

    return policy


def parse(protocol, text):
    policies = yaml.full_load(text)
    for p in policies:
        p["policy"] = from_ast(protocol, model.parse(p["policy"]))
    return policies


class Remind:
    """
    A helper class for defining remind policies.

    The following statement returns a function that returns a list of all Accept messages that do not have corresponding Deliver instances in the history.
      Remind(Accept).until.received(Deliver)
    """

    def __init__(self, *schemas):
        """List of message schemas to try reminding"""
        self.schemas = schemas
        self.reactors = {}
        self.reactive = False
        self.disjunctive = True
        self.priority = None
        self.delay = None
        self.generators = {}
        self.map = {}
        self.key = "reminders"

        # the set of active messages, for proactive policies
        self.active = set()

        # expectations in disjunctive normal form [[a & b] | [c & d]]
        self.expectations = []

    def run(self, history):
        return self.process(history)

    async def action(self, adapter, schema, context):
        # remind message
        for m in context.messages(schema):
            reminder = map_message(self.map, self.key, m)
            adapter.send(reminder)

    def With(self, map):
        self.map = map
        return self

    def after(self, delay):
        self.delay = delay
        return self

    @property
    def until(self):
        self.reactive = False
        return self

    def received(self, *expectations):
        """
        Reactively, remind whenever any of the expected messages are received.
        E.g.:
          Remind(A).upon.received(B)

        Proactively, select messages for which not all of the listed expectations have been received.
        E.g.:
          Remind(A).until.received(B,C)
        will remind A until /both/ B and C are received.

        To handle a disjunction, use separate received() clauses.
        E.g.:
          Remind(A).until.received(B).Or.received(C)
        """

        self.expectations.append(expectations)
        return self

    @property
    def Or(self):
        """Separator between received() clauses"""
        return self

    @property
    def upon(self):
        self.reactive = True
        return self

    def build(self):
        if self.reactive:
            for group in self.expectations:
                for s in group:

                    async def reactor(msg):
                        context = msg.adapter.history.context(msg)
                        for r in self.schemas:
                            # remind message schema r in the same context as msg
                            await self.action(msg.adapter, r, context)

                    self.reactors[s] = reactor
        else:

            async def activate(message):
                for group in self.expectations:
                    if all(message.context(e).find(e) for e in group):
                        # Don't activate if any conditions are already met
                        return
                message.meta["sent"] = datetime.datetime.now()
                self.active.add(message)

            for s in self.schemas:
                self.reactors[s] = activate

            async def deactivate(message):
                for s in self.schemas:
                    m = message.context(s).find(s)
                    if m and m in self.active:
                        for group in self.expectations:
                            # deactivate if all of any group of expectations are met
                            if all(message.context(e).find(e) for e in group):
                                self.active.remove(m)
                                break

            for g in self.expectations:
                for e in g:
                    self.reactors[e] = deactivate

    def process(self, history):
        messages = []
        if not self.delay:
            for m in self.active:
                reminder = map_message(self.map, self.key, m)
                messages.append(reminder)
                if len(messages) >= 500:
                    break
        else:
            now = datetime.datetime.now()
            for m in self.active:
                if (now - m.meta["sent"]).total_seconds() >= self.delay:
                    r = map_message(self.map, self.key, m)
                    messages.append(r)
                    # logger.debug(f"Sending {r} as {self.key} for {m}")
                if len(messages) >= 500:
                    break
        logger.debug(f"Sending {len(messages)} reminders for {self.schemas}")
        return messages

    def install(self, adapter, scheduler=None):
        if not self.reactors:
            self.build()
        for schema, reactor in self.reactors.items():
            adapter.register_reactor(schema, reactor, self.priority)

        if scheduler:
            scheduler.add(self)


class Forward(Remind):
    """
    Forwarding policy; sends a message to a specified recipient.
    E.g.: Forward(Deliver).to(Seller).upon.received(Deliver)
    """

    def __init__(self, *schemas):
        super().__init__(*schemas)
        self.recipient = None
        self.key = "forwards"
        self.reactive = True

    def to(self, recipient):
        self.recipient = recipient
        return self

    def observed(self, *schemas):
        return self.received(*schemas)


Send = Forward  # alias
