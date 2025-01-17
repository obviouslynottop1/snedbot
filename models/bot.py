import asyncio
import functools
import logging
import os
import pathlib
import typing as t

import hikari
import kosu
import lightbulb
import miru
from hikari.snowflakes import Snowflake

import utils.db_backup as db_backup
from config import Config
from etc import constants as const
from models.db import Database
from models.errors import UserBlacklistedError
from utils import cache
from utils import helpers
from utils import scheduler
from utils.tasks import IntervalLoop

from .context import *


async def get_prefix(bot: lightbulb.BotApp, message: hikari.Message) -> t.Union[t.Tuple[str], str]:
    """
    Get custom prefix for guild to show prefix command deprecation warn
    """
    assert isinstance(bot, SnedBot)
    if message.guild_id is None:
        return "sn "

    records = await bot.db_cache.get(table="global_config", guild_id=message.guild_id, limit=1)
    if records and records[0]["prefix"]:
        return tuple(records[0]["prefix"])

    return "sn "


async def is_not_blacklisted(ctx: SnedContext) -> bool:
    """Evaluate if the user is blacklisted or not.

    Parameters
    ----------
    ctx : SnedContext
        The context to evaluate under.

    Returns
    -------
    bool
        A boolean determining if the user is blacklisted or not.

    Raises
    ------
    UserBlacklistedError
        The user is blacklisted.
    """
    records = await ctx.app.db_cache.get(table="blacklist", user_id=ctx.user.id)

    if not records:
        return True

    raise UserBlacklistedError("User is blacklisted from using the application.")


class SnedBot(lightbulb.BotApp):
    """A customized subclass of lightbulb.BotApp

    Parameters
    ----------
    config : Config
        The bot configuration to initialize the bot with.
        See the included config_example.py for formatting help.
    """

    def __init__(self, config: Config) -> None:
        self.loop = asyncio.get_event_loop()
        self._started = asyncio.Event()
        self._is_started = False

        cache_settings = hikari.CacheSettings(
            components=hikari.CacheComponents.ALL, max_messages=10000, max_dm_channel_ids=50
        )
        intents = (
            hikari.Intents.GUILDS
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_BANS
            | hikari.Intents.GUILD_EMOJIS
            | hikari.Intents.GUILD_INVITES
            | hikari.Intents.ALL_MESSAGE_REACTIONS
            | hikari.Intents.ALL_MESSAGES
        )

        self.dev_mode: bool = config.DEV_MODE

        default_enabled_guilds = (config.DEBUG_GUILDS or ()) if self.dev_mode else ()

        token = os.getenv("TOKEN")

        if not token:
            raise RuntimeError("TOKEN not found in environment.")

        super().__init__(
            token=token,
            cache_settings=cache_settings,
            default_enabled_guilds=default_enabled_guilds,
            intents=intents,
            owner_ids=(163979124820541440,),
            prefix="dev",
            help_class=None,
        )

        # Initizaling configuration and database
        self._config = config
        self._db = Database(self)
        miru.load(self)

        # Some global variables
        self._base_dir = str(pathlib.Path(os.path.abspath(__file__)).parents[1])
        self._db_backup_loop = IntervalLoop(self.backup_db, seconds=3600 * 24)
        self.skip_first_db_backup = True  # Set to False to backup DB on bot startup too
        self._user_id: t.Optional[Snowflake] = None
        self._perspective: t.Optional[kosu.Client] = None
        self._initial_guilds: t.List[Snowflake] = []

        self.check(is_not_blacklisted)

        self.start_listeners()

    @property
    def user_id(self) -> Snowflake:
        """The application user's ID."""
        if self._user_id is None:
            raise hikari.ComponentStateConflictError("The bot is not yet initialized, user_id is unavailable.")

        return self._user_id

    @property
    def is_ready(self) -> bool:
        """Indicates if the application is ready to accept instructions or not.
        Alias for BotApp.is_alive"""
        return self.is_alive

    @property
    def base_dir(self) -> str:
        """The absolute path to the bot's project."""
        return self._base_dir

    @property
    def db(self) -> Database:
        """The main database connection pool of the bot."""
        return self._db

    @property
    def perspective(self) -> kosu.Client:
        """The perspective client of the bot."""
        if self._perspective is None:
            raise hikari.ComponentStateConflictError(
                "The bot is not initialized or no perspective API key was found in the environment."
            )
        return self._perspective

    @property
    def config(self) -> Config:
        """The passed configuration object."""
        return self._config

    @property
    def is_started(self) -> bool:
        """Boolean indicating if the bot has started up or not."""
        return self._is_started

    def start_listeners(self) -> None:
        """
        Start all listeners located in this class.
        """
        self.subscribe(hikari.StartingEvent, self.on_starting)
        self.subscribe(hikari.StartedEvent, self.on_started)
        self.subscribe(hikari.GuildAvailableEvent, self.on_guild_available)
        self.subscribe(lightbulb.LightbulbStartedEvent, self.on_lightbulb_started)
        self.subscribe(hikari.MessageCreateEvent, self.on_message)
        self.subscribe(hikari.StoppingEvent, self.on_stopping)
        self.subscribe(hikari.StoppedEvent, self.on_stop)
        self.subscribe(hikari.GuildJoinEvent, self.on_guild_join)
        self.subscribe(hikari.GuildLeaveEvent, self.on_guild_leave)

    async def wait_until_started(self) -> None:
        """
        Wait until the bot has started up
        """
        await asyncio.wait_for(self._started.wait(), timeout=None)

    async def get_slash_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.SlashCommand,
        cls: t.Type[lightbulb.SlashContext] = SnedSlashContext,
    ) -> SnedSlashContext:
        return await super().get_slash_context(event, command, cls)  # type: ignore

    async def get_user_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.UserCommand,
        cls: t.Type[lightbulb.UserContext] = SnedUserContext,
    ) -> SnedUserContext:
        return await super().get_user_context(event, command, cls)  # type: ignore

    async def get_message_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.MessageCommand,
        cls: t.Type[lightbulb.MessageContext] = SnedMessageContext,
    ) -> SnedMessageContext:
        return await super().get_message_context(event, command, cls)  # type: ignore

    async def get_prefix_context(
        self, event: hikari.MessageCreateEvent, cls: t.Type[lightbulb.PrefixContext] = SnedPrefixContext
    ) -> t.Optional[SnedPrefixContext]:
        return await super().get_prefix_context(event, cls)  # type: ignore

    async def on_guild_available(self, event: hikari.GuildAvailableEvent) -> None:
        if self.is_started:
            return
        self._initial_guilds.append(event.guild_id)

    async def on_starting(self, event: hikari.StartingEvent) -> None:
        # Connect to the database, create asyncpg pool
        await self.db.connect()
        # Create all the initial tables if they do not exist already
        with open(os.path.join(self.base_dir, "db", "schema.sql")) as file:
            await self.db.execute(file.read())

    async def on_started(self, event: hikari.StartedEvent) -> None:

        user = self.get_me()
        self._user_id = user.id if user else None
        self.db_cache = cache.DatabaseCache(self)
        self.scheduler = scheduler.Scheduler(self)

        if perspective_api_key := os.getenv("PERSPECTIVE_API_KEY"):
            self._perspective = kosu.Client(perspective_api_key, do_not_store=True)

        self._db_backup_loop.start()

        logging.info(f"Startup complete, initialized as {user}")
        activity = hikari.Activity(name="@Sned", type=hikari.ActivityType.LISTENING)
        await self.update_presence(activity=activity)

        if self.dev_mode:
            logging.warning("Developer mode is enabled!")

    async def on_lightbulb_started(self, event: lightbulb.LightbulbStartedEvent) -> None:

        # Insert all guilds the bot is member of into the db global config on startup
        async with self.db.acquire() as con:
            for guild_id in self._initial_guilds:
                await con.execute(
                    """
                    INSERT INTO global_config (guild_id) VALUES ($1)
                    ON CONFLICT (guild_id) DO NOTHING""",
                    guild_id,
                )
            logging.info(f"Connected to {len(self._initial_guilds)} guilds.")
            self._initial_guilds = []

        # Set this here so all guild_ids are in DB
        self._started.set()
        self._is_started = True
        self.unsubscribe(hikari.GuildAvailableEvent, self.on_guild_available)

    async def on_stopping(self, event: hikari.StoppingEvent) -> None:
        logging.info("Bot is shutting down...")

    async def on_stop(self, event: hikari.StoppedEvent) -> None:
        await self.db.close()
        logging.info("Closed database connection.")

    async def on_message(self, event: hikari.MessageCreateEvent) -> None:
        if not event.content:
            return

        if self.is_ready and self.db_cache.is_ready and event.is_human:
            mentions = [f"<@{self.user_id}>", f"<@!{self.user_id}>"]

            if event.content in mentions:
                embed = hikari.Embed(
                    title="Beep Boop!",
                    description="Use `/` to access my commands and see what I can do!",
                    color=0xFEC01D,
                )
                user = self.get_me()
                embed.set_thumbnail(user.avatar_url if user else None)
                await event.message.respond(embed=embed)
                return

            elif not event.content in await get_prefix(self, event.message) and event.content.startswith(
                await get_prefix(self, event.message)
            ):
                embed = hikari.Embed(
                    title="Uh Oh!",
                    description="This bot has transitioned to slash commands, to see a list of all commands, type `/`!\nIf you have any questions, or feel lost, feel free to join the [support server](https://discord.gg/KNKr8FPmJa)!",
                    color=const.ERROR_COLOR,
                )
                user = self.get_me()
                embed.set_thumbnail(user.avatar_url if user else None)
                await event.message.respond(embed=embed)
                return

    async def on_guild_join(self, event: hikari.GuildJoinEvent) -> None:
        """Guild join behaviour"""
        await self.db.execute(
            "INSERT INTO global_config (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING", event.guild_id
        )

        if event.guild.system_channel_id is None:
            return

        me = event.guild.get_my_member()
        channel = event.guild.get_channel(event.guild.system_channel_id)

        assert me is not None
        assert isinstance(channel, hikari.TextableGuildChannel)

        if not channel or not (hikari.Permissions.SEND_MESSAGES & lightbulb.utils.permissions_in(channel, me)):
            return

        try:
            embed = hikari.Embed(
                title="Beep Boop!",
                description="""I have been summoned to this server. Type `/` to see what I can do!\n\nIf you have `Manage Server` permissions, you may configure the bot via `/settings`!""",
                color=0xFEC01D,
            )
            embed.set_thumbnail(me.avatar_url)
            await channel.send(embed=embed)
        except hikari.ForbiddenError:
            pass
        logging.info(f"Bot has been added to new guild: {event.guild.name} ({event.guild_id}).")

    async def on_guild_leave(self, event: hikari.GuildLeaveEvent) -> None:
        """Guild removal behaviour"""
        await self.db.wipe_guild(event.guild_id, keep_record=False)
        logging.info(f"Bot has been removed from guild {event.guild_id}, correlating data erased.")

    async def backup_db(self) -> None:
        if self.skip_first_db_backup:
            logging.info("Skipping database backup for this day...")
            self.skip_first_db_backup = False
            return

        file = await db_backup.backup_database()
        await self.wait_until_started()

        if self.config.DB_BACKUP_CHANNEL:
            await self.rest.create_message(
                self.config.DB_BACKUP_CHANNEL,
                f"Database Backup: {helpers.format_dt(helpers.utcnow())}",
                attachment=file,
            )
            return logging.info("Database backup complete, database backed up to specified Discord channel.")

        logging.info("Database backup complete.")

    @functools.wraps(lightbulb.BotApp.run)
    def run(self, *args, **kwargs) -> None:
        self.load_extensions_from(os.path.join(self.base_dir, "extensions"), must_exist=True)
        super().run(*args, **kwargs)
