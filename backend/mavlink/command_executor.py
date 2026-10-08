import asyncio

class CommandExecutor:
    def __init__(self, guard, commands, event_bus):
        self.guard = guard
        self.commands = commands
        self.event_bus = event_bus

    async def execute(self, command, **kwargs):
        allowed, reason = await self.guard.validate(command)

        if not allowed:
            return {
                "success": False,
                "reason": reason
            }

        # Call MAVLink command
        result = await asyncio.to_thread(
            self.commands.execute,
            command,
            **kwargs
        )

        await self.event_bus.publish({
            "type": "command_executed",
            "command": command.value,
            "result": result
        })

        return {
            "success": True,
            "result": result
        }