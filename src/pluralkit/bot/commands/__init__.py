import os

import discord
import logging
import re
import traceback
from typing import Tuple, Optional, Union

from pluralkit import db
from pluralkit.system import System
from pluralkit.member import Member
from pluralkit.bot import embeds, utils

logger = logging.getLogger("pluralkit.bot.commands")


def next_arg(arg_string: str) -> Tuple[str, Optional[str]]:
    if arg_string.startswith("\""):
        end_quote = arg_string[1:].find("\"") + 1
        if end_quote > 0:
            return arg_string[1:end_quote], arg_string[end_quote + 1:].strip()
        else:
            return arg_string[1:], None

    next_space = arg_string.find(" ")
    if next_space >= 0:
        return arg_string[:next_space].strip(), arg_string[next_space:].strip()
    else:
        return arg_string.strip(), None


class CommandResponse:
    def to_embed(self):
        pass


class CommandSuccess(CommandResponse):
    def __init__(self, text):
        self.text = text

    def to_embed(self):
        return embeds.success("\u2705 " + self.text)


class CommandError(Exception, CommandResponse):
    def __init__(self, text: str, help: Tuple[str, str] = None):
        self.text = text
        self.help = help

    def to_embed(self):
        return embeds.error("\u274c " + self.text, self.help)


class CommandContext:
    def __init__(self, client: discord.Client, message: discord.Message, conn, args: str):
        self.client = client
        self.message = message
        self.conn = conn
        self.args = args

    async def get_system(self) -> Optional[System]:
        return await db.get_system_by_account(self.conn, self.message.author.id)

    async def ensure_system(self) -> System:
        system = await self.get_system()

        if not system:
            raise CommandError("No system registered to this account. Use `pk;system new` to register one.")

        return system

    def has_next(self) -> bool:
        return bool(self.args)

    def pop_str(self, error: CommandError = None) -> str:
        if not self.args:
            if error:
                raise error
            return None

        popped, self.args = next_arg(self.args)
        return popped

    async def pop_system(self, error: CommandError = None) -> System:
        name = self.pop_str(error)
        system = await utils.get_system_fuzzy(self.conn, self.client, name)

        if not system:
            raise CommandError("Unable to find system '{}'.".format(name))

        return system

    async def pop_member(self, error: CommandError = None, system_only: bool = True) -> Member:
        name = self.pop_str(error)

        if system_only:
            system = await self.ensure_system()
        else:
            system = await self.get_system()

        member = await utils.get_member_fuzzy(self.conn, system.id if system else None, name, system_only)
        if not member:
            raise CommandError("Unable to find member '{}'{}.".format(name, " in your system" if system_only else ""))

        return member

    def remaining(self):
        return self.args

    async def reply(self, content=None, embed=None):
        return await self.client.send_message(self.message.channel, content=content, embed=embed)

    async def confirm_react(self, user: Union[discord.Member, discord.User], message: str):
        message = await self.reply(message)

        await self.client.add_reaction(message, "✅")
        await self.client.add_reaction(message, "❌")

        reaction = await self.client.wait_for_reaction(emoji=["✅", "❌"], user=user, timeout=60.0*5)
        if not reaction:
            raise CommandError("Timed out - try again.")
        return reaction.reaction.emoji == "✅"

    async def confirm_text(self, user: discord.Member, channel: discord.Channel, confirm_text: str, message: str):
        await self.reply(message)

        message = await self.client.wait_for_message(channel=channel, author=user, timeout=60.0*5)
        if not message:
            raise CommandError("Timed out - try again.")
        return message.content == confirm_text


import pluralkit.bot.commands.import_commands
import pluralkit.bot.commands.member_commands
import pluralkit.bot.commands.message_commands
import pluralkit.bot.commands.misc_commands
import pluralkit.bot.commands.mod_commands
import pluralkit.bot.commands.switch_commands
import pluralkit.bot.commands.system_commands


async def log_error_in_channel(ctx: CommandContext):
    channel_id = os.environ["LOG_CHANNEL"]
    if not channel_id:
        return

    channel = ctx.client.get_channel(channel_id)

    embed = discord.Embed()
    embed.colour = discord.Colour.dark_red()
    embed.title = ctx.message.content

    embed.set_footer(text="Sender: {}#{} | Server: {} | Channel: {}".format(
        ctx.message.author.name, ctx.message.author.discriminator,
        ctx.message.server.id if ctx.message.server else "(DMs)",
        ctx.message.channel.id
    ))

    await ctx.client.send_message(channel, "```python\n{}```".format(traceback.format_exc()), embed=embed)


async def run_command(ctx: CommandContext, func):
    try:
        result = await func(ctx)
        if isinstance(result, CommandResponse):
            await ctx.reply(embed=result.to_embed())
    except CommandError as e:
        await ctx.reply(embed=e.to_embed())
    except Exception as e:
        logger.exception("Exception while dispatching command")

        await log_error_in_channel(ctx)


async def command_dispatch(client: discord.Client, message: discord.Message, conn) -> bool:
    prefix = "^pk(;|!)"
    commands = [
        (r"system (new|register|create|init)", system_commands.new_system),
        (r"system set", system_commands.system_set),
        (r"system link", system_commands.system_link),
        (r"system unlink", system_commands.system_unlink),
        (r"system fronter", system_commands.system_fronter),
        (r"system fronthistory", system_commands.system_fronthistory),
        (r"system (delete|remove|destroy|erase)", system_commands.system_delete),
        (r"system frontpercent(age)?", system_commands.system_frontpercent),
        (r"system", system_commands.system_info),

        (r"import tupperware", import_commands.import_tupperware),

        (r"member (new|create|add|register)", member_commands.new_member),
        (r"member set", member_commands.member_set),
        (r"member proxy", member_commands.member_proxy),
        (r"member (delete|remove|destroy|erase)", member_commands.member_delete),
        (r"member", member_commands.member_info),

        (r"message", message_commands.message_info),

        (r"mod log", mod_commands.set_log),

        (r"invite", misc_commands.invite_link),
        (r"export", misc_commands.export),

        (r"help", misc_commands.show_help),

        (r"switch move", switch_commands.switch_move),
        (r"switch out", switch_commands.switch_out),
        (r"switch", switch_commands.switch_member)
    ]

    for pattern, func in commands:
        regex = re.compile(prefix + pattern, re.IGNORECASE)

        cmd = message.content
        match = regex.match(cmd)
        if match:
            remaining_string = cmd[match.span()[1]:].strip()

            ctx = CommandContext(
                client=client,
                message=message,
                conn=conn,
                args=remaining_string
            )

            await run_command(ctx, func)
            return True
    return False
