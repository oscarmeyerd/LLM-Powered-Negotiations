#!/usr/bin/env python3


class Event:
    def __init__(self, type=None):
        if type:
            self.type = type


class ObservationEvent(Event):
    type = None
    messages = []


class ReceptionEvent(ObservationEvent):
    def __init__(self, message):
        self.type = "reception"
        self.messages = [message]


class EmissionEvent(ObservationEvent):
    def __init__(self, messages):
        self.type = "emission"
        self.messages = messages


class InitEvent(Event):
    type = "init"
