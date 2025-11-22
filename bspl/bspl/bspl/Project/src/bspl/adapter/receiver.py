import asyncio
import socket
import json
import ijson
import datetime
from asyncio.queues import Queue
from .message import Message


def unbundle(bundle):
    return bundle


def decode(msg):
    return json.loads(msg)


class UDPReceiverProtocol:
    def __init__(self, queue, adapter):
        self.queue = queue
        self.adapter = adapter

    def datagram_received(self, data, addr):
        self.queue.put_nowait(data)

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        adapter.debug(f"Connection lost: {exc}")


class Receiver:
    """An Receiver just needs the send(message) method."""

    def __init__(self, address, decoder=decode, unbundler=unbundle):
        self.address = address
        self.decode = decoder
        self.unbundle = unbundler
        self.listening = False

    async def task(self, adapter):
        """Start loop for transmitting messages in outgoing queue"""
        self.adapter = adapter
        self.queue = Queue()
        loop = asyncio.get_running_loop()
        adapter.debug(f"Attempting to bind: {self.address}")
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPReceiverProtocol(self.queue, adapter),
            local_addr=(self.address[0], self.address[1]),
        )
        self.listening = True
        self.transport = transport
        adapter.debug(f"Listening on {self.address}")
        loop.create_task(self.process())

    async def process(self):
        while self.listening:
            data = await self.queue.get()
            bundle = self.decode(data)
            messages = self.unbundle(bundle)
            for m in messages:
                await self.adapter.receive(m)
        self.adapter.info("Stopped listening")

    async def stop(self):
        self.listening = False
        self.transport.close()


class MockReceiver:
    """
    A mock receiver that doesn't bind to any network ports.
    Only useful for testing - doesn't actually receive any network data.
    """
    def __init__(self, address=None, decoder=decode, unbundler=unbundle):
        self.address = address or ("localhost", 0)  # Use any free port
        self.decode = decoder
        self.unbundle = unbundler
        self.listening = False
        self.received_messages = []
    
    async def task(self, adapter):
        """Start the mock receiver (doesn't actually bind to any ports)"""
        self.adapter = adapter
        self.queue = Queue()
        self.listening = True
        adapter.debug(f"Mock receiver initialized (no sockets bound)")
    
    async def inject_message(self, message):
        """Simulate receiving a message from the network"""
        if self.listening and hasattr(self, 'adapter'):
            self.received_messages.append(message)
            await self.adapter.receive(message.serialize())
            return True
        return False
    
    async def stop(self):
        """Stop the mock receiver"""
        self.listening = False
        if hasattr(self, 'adapter'):
            self.adapter.debug(f"Mock receiver stopped")


class TCPReceiver:
    def __init__(self, address, decoder=decode):
        self.address = address
        self.decode = decoder

    async def task(self, adapter):
        self.adapter = adapter
        self.queue = Queue()
        loop = asyncio.get_running_loop()

        server = await asyncio.start_server(self.process, "0.0.0.0", self.address[1])
        self.server = server

        addr = server.sockets[0].getsockname()
        adapter.info(f"Listening on {addr}")

        loop = asyncio.get_running_loop()

        async def serve():
            async with server:
                await server.serve_forever()

        loop.create_task(serve())

    async def process(self, reader, writer):
        async for obj in ijson.items(reader, "item"):
            await self.adapter.receive(obj)

    async def stop(self):
        await self.server.close()
