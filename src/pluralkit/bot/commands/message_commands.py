from pluralkit.bot import help
from pluralkit.bot.commands import *

logger = logging.getLogger("pluralkit.commands")


async def message_info(ctx: CommandContext):
    mid_str = ctx.pop_str(CommandError("You must pass a message ID.", help=help.message_lookup))

    try:
        mid = int(mid_str)
    except ValueError:
        return CommandError("You must pass a valid number as a message ID.", help=help.message_lookup)

    # Find the message in the DB
    message = await db.get_message(ctx.conn, str(mid))
    if not message:
        raise CommandError("Message with ID '{}' not found.".format(mid))

    # Get the original sender of the messages
    try:
        original_sender = await ctx.client.get_user_info(str(message.sender))
    except discord.NotFound:
        # Account was since deleted - rare but we're handling it anyway
        original_sender = None

    embed = discord.Embed()
    embed.timestamp = discord.utils.snowflake_time(str(mid))
    embed.colour = discord.Colour.blue()

    if message.system_name:
        system_value = "{} (`{}`)".format(message.system_name, message.system_hid)
    else:
        system_value = "`{}`".format(message.system_hid)
    embed.add_field(name="System", value=system_value)

    embed.add_field(name="Member", value="{} (`{}`)".format(message.name, message.hid))

    if original_sender:
        sender_name = "{}#{}".format(original_sender.name, original_sender.discriminator)
    else:
        sender_name = "(deleted account {})".format(message.sender)

    embed.add_field(name="Sent by", value=sender_name)

    if message.content:  # Content can be empty string if there's an attachment
        embed.add_field(name="Content", value=message.content, inline=False)

    embed.set_author(name=message.name, icon_url=message.avatar_url or discord.Embed.Empty)

    await ctx.reply(embed=embed)
