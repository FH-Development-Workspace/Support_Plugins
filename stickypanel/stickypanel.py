"""
FH Development - Sticky Panel
=============================

Components V2 edition.

Originally based on:
https://github.com/Ollieg3/Modmail-Plugins

Reworked for FH Development with:
- Discord Components V2
- FH Development branding
- Modern blue / white / black styling
- Persistent ticket controls
- Category-specific buttons
- Configurable buttons and categories
- Automatic sticky panel refreshing
- Modmail alias/snippet support
"""

import asyncio
import copy
import json
import os

import discord
from discord.ext import commands


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_PATH = "sticky_panel_config.json"

FH_BLUE = 0x5865F2
FH_DARK = 0x0F1117
FH_WHITE = 0xFFFFFF

PANEL_FOOTER = "FH Development • Support Centre"

PANEL_FOOTER_TEXT = (
    "FH Development • Support Centre\n"
    "Use the controls below to manage this ticket."
)

DEFAULT_TITLE = "Ticket Control"
DEFAULT_DESCRIPTION = (
    "Manage this support ticket using the controls below."
)
DEFAULT_DELAY = 5.0

DEFAULT_CONFIG = {
    "enabled": False,
    "delay": DEFAULT_DELAY,
    "title": DEFAULT_TITLE,
    "description": DEFAULT_DESCRIPTION,
    "color": FH_BLUE,
    "categories": [],
    "buttons": []
}


# Discord limits
MAX_ROWS = 4
MAX_PER_ROW = 5
MAX_SELECT_OPTIONS = 25


# ============================================================
# BUTTON STYLES
# ============================================================

STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,

    # Friendly aliases
    "blurple": discord.ButtonStyle.primary,
    "blue": discord.ButtonStyle.primary,
    "grey": discord.ButtonStyle.secondary,
    "gray": discord.ButtonStyle.secondary,
    "green": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
}


# ============================================================
# SAFE JSON HANDLING
# ============================================================

def save_config(config):
    tmp_path = f"{CONFIG_PATH}.tmp"

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)

        os.replace(tmp_path, CONFIG_PATH)

    except Exception as e:
        print(f"[FH StickyPanel] Error saving config: {e}")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config)
        return config

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("config is not a JSON object")

    except Exception as e:
        backup = f"{CONFIG_PATH}.broken"

        print(
            f"[FH StickyPanel] Config load failed ({e}). "
            f"Backed up to {backup} and reverted to default."
        )

        try:
            os.replace(CONFIG_PATH, backup)
        except OSError:
            pass

        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config)
        return config

    for key, value in DEFAULT_CONFIG.items():
        data.setdefault(key, copy.deepcopy(value))

    return data


# ============================================================
# HELPERS
# ============================================================

def truncate(text, limit):
    text = str(text)

    if len(text) <= limit:
        return text

    return text[: limit - 1] + "…"


def clamp_row(value):
    try:
        row = int(value)
    except (TypeError, ValueError):
        row = 1

    return min(max(row, 1), MAX_ROWS)


def strip_prefix(text, prefix):
    text = text.strip()

    for p in {prefix, "-"}:
        while p and text.startswith(p):
            text = text[len(p):].strip()

    return text


def buttons_for_scope(buttons, category_id):
    """
    Universal buttons are shown everywhere.

    Category-locked buttons are only shown when the current
    ticket is inside their configured category.
    """

    return [
        b
        for b in buttons
        if not b.get("category_id")
        or b.get("category_id") == category_id
    ]


def build_category_options(categories):
    options = []
    mapping = {}

    for cat in categories:
        value = str(cat.get("value", "")).strip()

        if not value:
            continue

        if value in mapping:
            continue

        if len(options) >= MAX_SELECT_OPTIONS:
            break

        mapping[value] = cat

        description = cat.get("description")

        options.append(
            discord.SelectOption(
                label=truncate(
                    cat.get("label") or value,
                    100
                ),
                value=value,
                description=(
                    truncate(description, 100)
                    if description
                    else None
                ),
                emoji=cat.get("emoji") or None
            )
        )

    return options, mapping


def parse_color(value):
    if isinstance(value, int):
        return value

    if isinstance(value, str):
        try:
            return int(
                value.strip()
                .lstrip("#"),
                16
            )
        except ValueError:
            pass

    return FH_BLUE


# ============================================================
# COMPONENTS V2 HELPERS
# ============================================================

def make_text(content):
    """
    Creates a Components V2 TextDisplay.
    """

    return discord.ui.TextDisplay(content)


def make_separator():
    return discord.ui.Separator()


def make_action_row(*items):
    """
    Components V2 ActionRow.

    Buttons and selects must live inside an ActionRow.
    """

    row = discord.ui.ActionRow()

    for item in items:
        row.add_item(item)

    return row


# ============================================================
# ADD BUTTON MODAL
# ============================================================

class AddButtonModal(
    discord.ui.Modal,
    title="Add / Edit Action Button"
):

    label_input = discord.ui.TextInput(
        label="Button Label",
        placeholder="e.g. Refund",
        max_length=80,
        required=True
    )

    alias_input = discord.ui.TextInput(
        label="Command Alias",
        placeholder="e.g. refund",
        max_length=50,
        required=True
    )

    category_input = discord.ui.TextInput(
        label="Category ID (Optional)",
        placeholder="e.g. 123456789012345678",
        max_length=100,
        required=False
    )

    style_input = discord.ui.TextInput(
        label="Style",
        placeholder="blue / grey / green / red",
        default="blue",
        max_length=20,
        required=False
    )

    row_input = discord.ui.TextInput(
        label="Row (1-4)",
        placeholder="1",
        default="1",
        max_length=1,
        required=False
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        cog = self.cog
        buttons = cog.config["buttons"]

        label_val = self.label_input.value.strip()

        if not label_val:
            return await interaction.response.send_message(
                "❌ Button label cannot be empty.",
                ephemeral=True
            )

        alias_val = strip_prefix(
            self.alias_input.value,
            cog.prefix
        )

        if not alias_val:
            return await interaction.response.send_message(
                "❌ Alias cannot be empty.",
                ephemeral=True
            )

        cat_target = (
            self.category_input.value.strip()
            or None
        )

        if cat_target and not cat_target.isdigit():
            return await interaction.response.send_message(
                "❌ Category ID must be a number.",
                ephemeral=True
            )

        style_val = (
            self.style_input.value.strip().lower()
            or "blue"
        )

        if style_val not in STYLE_MAP:
            return await interaction.response.send_message(
                "❌ Invalid style. Use `blue`, `grey`, `green`, or `red`.",
                ephemeral=True
            )

        row_raw = (
            self.row_input.value.strip()
            or "1"
        )

        if not row_raw.isdigit():
            return await interaction.response.send_message(
                "❌ Row must be between 1 and 4.",
                ephemeral=True
            )

        row_val = clamp_row(row_raw)

        existing = next(
            (
                b for b in buttons
                if b.get("label", "").lower()
                == label_val.lower()
            ),
            None
        )

        others = [
            b for b in buttons
            if b is not existing
        ]

        if cat_target:
            scopes = {cat_target}
        else:
            scopes = {
                None
            } | {
                b.get("category_id")
                for b in others
                if b.get("category_id")
            }

        busiest = max(
            (
                sum(
                    1
                    for b in buttons_for_scope(
                        others,
                        scope
                    )
                    if clamp_row(
                        b.get("row", 1)
                    ) == row_val
                )
                for scope in scopes
            ),
            default=0
        )

        if busiest >= MAX_PER_ROW:
            return await interaction.response.send_message(
                f"❌ Row `{row_val}` already has 5 buttons.",
                ephemeral=True
            )

        data = {
            "label": label_val,
            "alias": alias_val,
            "style": style_val,
            "row": row_val,
            "category_id": cat_target
        }

        if existing:
            existing.update(data)
            action_type = "Updated"
        else:
            buttons.append(data)
            action_type = "Added"

        save_config(cog.config)

        lock_text = (
            f"`{cat_target}`"
            if cat_target
            else "Universal"
        )

        container = discord.ui.Container(
            make_text(
                f"## FH Development\n"
                f"### Button {action_type}\n\n"
                f"**Label:** {label_val}\n"
                f"**Command:** `{cog.prefix}{alias_val}`\n"
                f"**Row:** `{row_val}`\n"
                f"**Category:** {lock_text}"
            ),
            accent_colour=FH_BLUE
        )

        view = discord.ui.LayoutView()
        view.add_item(container)

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )


# ============================================================
# ADD CATEGORY MODAL
# ============================================================

class AddCategoryModal(
    discord.ui.Modal,
    title="Add / Edit Category"
):

    label_input = discord.ui.TextInput(
        label="Dropdown Label",
        placeholder="e.g. Billing",
        max_length=100,
        required=True
    )

    value_input = discord.ui.TextInput(
        label="Target Category ID",
        placeholder="e.g. 123456789012345678",
        max_length=100,
        required=True
    )

    emoji_input = discord.ui.TextInput(
        label="Emoji",
        placeholder="e.g. 💳",
        max_length=10,
        required=False
    )

    alias_input = discord.ui.TextInput(
        label="Auto-run Alias",
        placeholder="e.g. billing_snippet",
        max_length=50,
        required=False
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        cog = self.cog
        categories = cog.config["categories"]

        label_val = self.label_input.value.strip()
        value_val = self.value_input.value.strip()
        emoji_val = (
            self.emoji_input.value.strip()
            or None
        )
        alias_val = (
            strip_prefix(
                self.alias_input.value,
                cog.prefix
            )
            or None
        )

        if not label_val:
            return await interaction.response.send_message(
                "❌ Dropdown label cannot be empty.",
                ephemeral=True
            )

        if not value_val.isdigit():
            return await interaction.response.send_message(
                "❌ Category ID must be a number.",
                ephemeral=True
            )

        existing = next(
            (
                c for c in categories
                if c.get("label", "").lower()
                == label_val.lower()
            ),
            None
        )

        duplicate = next(
            (
                c for c in categories
                if c is not existing
                and str(c.get("value")) == value_val
            ),
            None
        )

        if duplicate:
            return await interaction.response.send_message(
                f"❌ That category ID is already used by "
                f"**{duplicate['label']}**.",
                ephemeral=True
            )

        if (
            not existing
            and len(categories) >= MAX_SELECT_OPTIONS
        ):
            return await interaction.response.send_message(
                "❌ You can only have 25 categories.",
                ephemeral=True
            )

        data = {
            "label": label_val,
            "value": value_val,
            "description": f"Move to {label_val}",
            "emoji": emoji_val,
            "alias": alias_val
        }

        if existing:
            existing.update(data)
            action_type = "Updated"
        else:
            categories.append(data)
            action_type = "Added"

        save_config(cog.config)

        container = discord.ui.Container(
            make_text(
                f"## FH Development\n"
                f"### Category {action_type}\n\n"
                f"**Name:** {emoji_val or ''} {label_val}\n"
                f"**Category ID:** `{value_val}`\n"
                f"**Auto-run:** "
                f"{f'`{cog.prefix}{alias_val}`' if alias_val else 'None'}"
            ),
            accent_colour=FH_BLUE
        )

        view = discord.ui.LayoutView()
        view.add_item(container)

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )


# ============================================================
# REMOVE BUTTON SELECT
# ============================================================

class RemoveButtonSelect(discord.ui.Select):

    def __init__(self, cog):
        self.cog = cog

        options = []

        for btn in cog.config["buttons"][
            :MAX_SELECT_OPTIONS
        ]:
            scope = (
                f"Category: {btn['category_id']}"
                if btn.get("category_id")
                else "Universal"
            )

            options.append(
                discord.SelectOption(
                    label=truncate(
                        btn["label"],
                        100
                    ),
                    value=btn["label"],
                    description=truncate(
                        f"Runs {cog.prefix}{btn['alias']} • {scope}",
                        100
                    )
                )
            )

        super().__init__(
            placeholder="Select a button to remove...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        selected_label = self.values[0]

        self.cog.config["buttons"] = [
            b
            for b in self.cog.config["buttons"]
            if b["label"] != selected_label
        ]

        save_config(self.cog.config)

        container = discord.ui.Container(
            make_text(
                f"## FH Development\n"
                f"### Button Removed\n\n"
                f"Successfully removed **{selected_label}**."
            ),
            accent_colour=FH_BLUE
        )

        view = discord.ui.LayoutView()
        view.add_item(container)

        await interaction.response.edit_message(
            view=view
        )


class RemoveButtonView(discord.ui.LayoutView):

    def __init__(self, cog):
        super().__init__(timeout=60)

        select = RemoveButtonSelect(cog)

        self.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Remove Button\n\n"
                    "Select the button you want to remove."
                ),
                make_separator(),
                make_action_row(select),
                accent_colour=FH_BLUE
            )
        )


# ============================================================
# REMOVE CATEGORY SELECT
# ============================================================

class RemoveCategorySelect(discord.ui.Select):

    def __init__(self, cog):
        self.cog = cog

        options = []

        for cat in cog.config["categories"][
            :MAX_SELECT_OPTIONS
        ]:
            options.append(
                discord.SelectOption(
                    label=truncate(
                        cat["label"],
                        100
                    ),
                    value=cat["label"],
                    description=truncate(
                        f"ID: {cat['value']}",
                        100
                    )
                )
            )

        super().__init__(
            placeholder="Select a category to remove...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        selected_label = self.values[0]

        self.cog.config["categories"] = [
            c
            for c in self.cog.config["categories"]
            if c["label"] != selected_label
        ]

        save_config(self.cog.config)

        container = discord.ui.Container(
            make_text(
                f"## FH Development\n"
                f"### Category Removed\n\n"
                f"Successfully removed **{selected_label}**."
            ),
            accent_colour=FH_BLUE
        )

        view = discord.ui.LayoutView()
        view.add_item(container)

        await interaction.response.edit_message(
            view=view
        )


class RemoveCategoryView(discord.ui.LayoutView):

    def __init__(self, cog):
        super().__init__(timeout=60)

        select = RemoveCategorySelect(cog)

        self.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Remove Category\n\n"
                    "Select the category you want to remove."
                ),
                make_separator(),
                make_action_row(select),
                accent_colour=FH_BLUE
            )
        )


# ============================================================
# PANEL BUTTON
# ============================================================

class PanelButton(discord.ui.Button):

    def __init__(
        self,
        cog,
        data: dict
    ):
        super().__init__(
            label=truncate(
                data["label"],
                80
            ),
            style=STYLE_MAP.get(
                str(
                    data.get(
                        "style",
                        "blue"
                    )
                ).lower(),
                discord.ButtonStyle.primary
            ),
            emoji=data.get("emoji") or None
        )

        self.cog = cog
        self.alias = data["alias"]

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if not await self.cog.is_modmail_thread(
            interaction.channel
        ):
            return await interaction.response.send_message(
                "This is not an active Modmail thread.",
                ephemeral=True
            )

        await interaction.response.defer()

        try:
            await self.cog.run_alias(
                interaction,
                self.alias
            )

        except Exception as e:
            print(
                f"[FH StickyPanel] Error running "
                f"'{self.alias}': {e}"
            )

            await interaction.followup.send(
                f"❌ Couldn't run "
                f"`{self.cog.prefix}{self.alias}`:\n"
                f"`{e}`",
                ephemeral=True
            )


# ============================================================
# CATEGORY DROPDOWN
# ============================================================

class CategorySelect(discord.ui.Select):

    def __init__(
        self,
        cog,
        options,
        mapping
    ):
        self.cog = cog
        self.mapping = mapping

        super().__init__(
            placeholder="📁 Move ticket to category...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if not await self.cog.is_modmail_thread(
            interaction.channel
        ):
            return await interaction.response.send_message(
                "This is not an active Modmail thread.",
                ephemeral=True
            )

        selected_value = self.values[0]

        alias_to_run = (
            self.mapping
            .get(selected_value, {})
            .get("alias")
        )

        await interaction.response.defer()

        try:
            await self.cog.run_alias(
                interaction,
                f"move {selected_value}"
            )

            if alias_to_run:
                await asyncio.sleep(0.5)

                await self.cog.run_alias(
                    interaction,
                    alias_to_run
                )

        except Exception as e:
            print(
                f"[FH StickyPanel] Category error: {e}"
            )

            await interaction.followup.send(
                f"❌ Something went wrong moving "
                f"the ticket:\n`{e}`",
                ephemeral=True
            )

        self.cog.schedule_resend(
            interaction.channel
        )


# ============================================================
# COMPONENTS V2 PANEL
# ============================================================

class StickyPanelView(discord.ui.LayoutView):

    def __init__(
        self,
        cog,
        channel
    ):
        super().__init__(timeout=None)

        config = cog.config

        options, mapping = build_category_options(
            config.get("categories", [])
        )

        current_cat_id = None

        if (
            isinstance(channel, discord.TextChannel)
            and channel.category
        ):
            current_cat_id = str(
                channel.category.id
            )

        buttons = buttons_for_scope(
            config.get("buttons", []),
            current_cat_id
        )

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        children = [
            make_text(
                f"# FH DEVELOPMENT\n"
                f"## {config.get('title') or DEFAULT_TITLE}\n\n"
                f"{config.get('description') or DEFAULT_DESCRIPTION}"
            ),
            make_separator()
        ]

        # ----------------------------------------------------
        # CATEGORY SELECT
        # ----------------------------------------------------

        if options:
            children.append(
                make_text("### Ticket Category")
            )

            children.append(
                make_action_row(
                    CategorySelect(
                        cog,
                        options,
                        mapping
                    )
                )
            )

            children.append(
                make_separator()
            )

        # ----------------------------------------------------
        # ACTION BUTTONS
        # ----------------------------------------------------

        valid_buttons = [
            b
            for b in buttons
            if b.get("label")
            and b.get("alias")
        ]

        if valid_buttons:
            children.append(
                make_text("### Ticket Actions")
            )

            row_counts = {
                r: 0
                for r in range(
                    1,
                    MAX_ROWS + 1
                )
            }

            rows = {
                r: []
                for r in range(
                    1,
                    MAX_ROWS + 1
                )
            }

            for btn in valid_buttons:
                wanted = clamp_row(
                    btn.get("row", 1)
                )

                search_order = (
                    list(
                        range(
                            wanted,
                            MAX_ROWS + 1
                        )
                    )
                    +
                    list(
                        range(
                            1,
                            wanted
                        )
                    )
                )

                row = next(
                    (
                        r
                        for r in search_order
                        if row_counts[r]
                        < MAX_PER_ROW
                    ),
                    None
                )

                if row is None:
                    print(
                        "[FH StickyPanel] No room for "
                        f"button '{btn['label']}'."
                    )
                    continue

                try:
                    button = PanelButton(
                        cog,
                        btn
                    )

                    rows[row].append(button)
                    row_counts[row] += 1

                except Exception as e:
                    print(
                        f"[FH StickyPanel] Invalid "
                        f"button '{btn.get('label')}': {e}"
                    )

            for row_number in range(
                1,
                MAX_ROWS + 1
            ):
                if rows[row_number]:
                    children.append(
                        make_action_row(
                            *rows[row_number]
                        )
                    )

        # ----------------------------------------------------
        # FOOTER
        # ----------------------------------------------------

        children.extend(
            [
                make_separator(),
                make_text(
                    f"-# {PANEL_FOOTER}\n"
                    f"-# Normal Modmail commands remain available."
                )
            ]
        )

        # ----------------------------------------------------
        # CONTAINER
        # ----------------------------------------------------

        self.add_item(
            discord.ui.Container(
                *children,
                accent_colour=parse_color(
                    config.get(
                        "color",
                        FH_BLUE
                    )
                )
            )
        )


# ============================================================
# MAIN COG
# ============================================================

class StickyPanel(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()

        self.sticky_messages = {}
        self.pending = {}
        self.locks = {}

    def cog_unload(self):
        for task in self.pending.values():
            task.cancel()

    @property
    def prefix(self):
        prefix = getattr(
            self.bot,
            "prefix",
            None
        )

        if (
            isinstance(prefix, str)
            and prefix
        ):
            return prefix

        return "-"

    def get_lock(self, channel_id):
        if channel_id not in self.locks:
            self.locks[channel_id] = asyncio.Lock()

        return self.locks[channel_id]

    # --------------------------------------------------------
    # MODMAIL DETECTION
    # --------------------------------------------------------

    async def is_modmail_thread(
        self,
        channel
    ):
        if (
            not isinstance(
                channel,
                discord.TextChannel
            )
            or not hasattr(
                self.bot,
                "threads"
            )
        ):
            return False

        try:
            return (
                await self.bot.threads.find(
                    channel=channel
                )
                is not None
            )

        except Exception:
            return False

    # --------------------------------------------------------
    # PANEL MESSAGE DETECTION
    # --------------------------------------------------------

    def is_panel_message(
        self,
        message
    ):
        if (
            not self.bot.user
            or message.author.id
            != self.bot.user.id
        ):
            return False

        # Components V2 messages don't use embeds.
        #
        # The safest way to identify our panel is through
        # the message's component structure / known content.
        #
        # Since Components V2 does not expose the same
        # embed-footer mechanism, check the message flags
        # and our tracked message ID.

        if message.id in self.sticky_messages.values():
            return True

        return False

    # --------------------------------------------------------
    # RUN MODMAIL ALIAS
    # --------------------------------------------------------

    async def run_alias(
        self,
        interaction,
        alias
    ):
        """
        Runs a Modmail command/alias/snippet as the user
        who clicked the component.
        """

        message = copy.copy(
            interaction.message
        )

        message.content = (
            f"{self.prefix}{alias}"
        )

        message.author = interaction.user

        await self.bot.process_commands(
            message
        )

    # --------------------------------------------------------
    # PANEL
    # --------------------------------------------------------

    def build_panel_view(
        self,
        channel
    ):
        return StickyPanelView(
            self,
            channel
        )

    # --------------------------------------------------------
    # RESENDING
    # --------------------------------------------------------

    def schedule_resend(
        self,
        channel,
        delay=None
    ):
        if (
            not self.config.get(
                "enabled",
                False
            )
            or not isinstance(
                channel,
                discord.TextChannel
            )
        ):
            return

        existing = self.pending.get(
            channel.id
        )

        if (
            existing
            and not existing.done()
        ):
            existing.cancel()

        if delay is None:
            try:
                delay = float(
                    self.config.get(
                        "delay",
                        DEFAULT_DELAY
                    )
                )

            except (
                TypeError,
                ValueError
            ):
                delay = DEFAULT_DELAY

        self.pending[channel.id] = (
            asyncio.create_task(
                self._resend_after(
                    channel,
                    delay
                )
            )
        )

    async def _resend_after(
        self,
        channel,
        delay
    ):
        try:
            await asyncio.sleep(delay)

        except asyncio.CancelledError:
            return

        if (
            self.pending.get(
                channel.id
            )
            is asyncio.current_task()
        ):
            self.pending.pop(
                channel.id,
                None
            )

        async with self.get_lock(
            channel.id
        ):
            try:
                await self._post_panel(
                    channel
                )

            except Exception as e:
                print(
                    f"[FH StickyPanel] Failed to "
                    f"resend panel in {channel.id}: {e}"
                )

    async def resend_sticky(
        self,
        channel
    ):
        self.schedule_resend(
            channel,
            delay=0
        )

    async def _clear_old_panels(
        self,
        channel
    ):
        """
        After a restart, find previous FH Components V2
        panels and remove them.

        We identify them using the bot's own messages
        containing Components V2.
        """

        try:
            async for msg in channel.history(
                limit=30
            ):
                if (
                    msg.author.id
                    != self.bot.user.id
                ):
                    continue

                if (
                    msg.id
                    in self.sticky_messages.values()
                ):
                    continue

                # Only inspect bot-authored messages
                # with components.
                if getattr(
                    msg,
                    "components",
                    None
                ):
                    try:
                        await msg.delete()

                    except discord.HTTPException:
                        pass

        except discord.HTTPException:
            pass

    async def _post_panel(
        self,
        channel
    ):
        old_msg_id = self.sticky_messages.pop(
            channel.id,
            None
        )

        if old_msg_id:
            try:
                await channel.get_partial_message(
                    old_msg_id
                ).delete()

            except discord.HTTPException:
                pass

        else:
            await self._clear_old_panels(
                channel
            )

        try:
            view = self.build_panel_view(
                channel
            )

            new_msg = await channel.send(
                view=view
            )

            self.sticky_messages[
                channel.id
            ] = new_msg.id

        except discord.HTTPException as e:
            print(
                f"[FH StickyPanel] Failed to send "
                f"panel in {channel.id}: {e}"
            )

    # ========================================================
    # ADMIN PANEL
    # ========================================================

    def build_settings_view(self):
        enabled = self.config.get(
            "enabled",
            False
        )

        delay = self.config.get(
            "delay",
            DEFAULT_DELAY
        )

        buttons = self.config.get(
            "buttons",
            []
        )

        categories = self.config.get(
            "categories",
            []
        )

        status = (
            "🟢 Enabled"
            if enabled
            else "🔴 Disabled"
        )

        button_lines = []

        for b in buttons:
            category = (
                f"`{b['category_id']}`"
                if b.get("category_id")
                else "Universal"
            )

            button_lines.append(
                f"• **{b['label']}** "
                f"`{self.prefix}{b['alias']}` "
                f"• Row `{clamp_row(b.get('row', 1))}` "
                f"• {category}"
            )

        category_lines = []

        for c in categories:
            alias = (
                f"`{self.prefix}{c['alias']}`"
                if c.get("alias")
                else "None"
            )

            category_lines.append(
                f"• {c.get('emoji') or '📁'} "
                f"**{c['label']}** "
                f"→ `{c['value']}` "
                f"• {alias}"
            )

        children = [
            make_text(
                "# FH DEVELOPMENT\n"
                "## Sticky Panel Settings\n\n"
                f"**Status:** {status}\n"
                f"**Delay:** `{delay}s`\n"
                f"**Title:** {truncate(self.config.get('title') or '-', 256)}"
            ),
            make_separator(),

            make_text(
                f"### Buttons ({len(buttons)})\n\n"
                + (
                    "\n".join(button_lines)
                    if button_lines
                    else "*No buttons configured.*"
                )
            ),

            make_separator(),

            make_text(
                f"### Categories ({len(categories)})\n\n"
                + (
                    "\n".join(category_lines)
                    if category_lines
                    else "*No categories configured.*"
                )
            ),

            make_separator(),

            make_text(
                "### Commands\n\n"
                f"`{self.prefix}stickypanel enable`\n"
                f"`{self.prefix}stickypanel disable`\n"
                f"`{self.prefix}stickypanel preview`\n"
                f"`{self.prefix}stickypanel refresh`\n"
                f"`{self.prefix}stickypanel addbutton`\n"
                f"`{self.prefix}stickypanel removebutton`\n"
                f"`{self.prefix}stickypanel addcategory`\n"
                f"`{self.prefix}stickypanel removecategory`\n"
                f"`{self.prefix}stickypanel title <text>`\n"
                f"`{self.prefix}stickypanel description <text>`\n"
                f"`{self.prefix}stickypanel delay <seconds>`\n"
                f"`{self.prefix}stickypanel color <#hex>`\n"
                f"`{self.prefix}stickypanel reset`"
            ),

            make_separator(),

            make_text(
                "-# FH Development • Sticky Panel"
            )
        ]

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                *children,
                accent_colour=FH_BLUE
            )
        )

        return view

    # ========================================================
    # COMMAND GROUP
    # ========================================================

    @commands.group(
        name="stickypanel",
        invoke_without_command=True
    )
    @commands.has_permissions(
        administrator=True
    )
    async def stickypanel_cmd(
        self,
        ctx
    ):
        await ctx.send(
            view=self.build_settings_view()
        )

    # ========================================================
    # ENABLE
    # ========================================================

    @stickypanel_cmd.command(
        name="enable"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def enable_panel(
        self,
        ctx
    ):
        self.config["enabled"] = True
        save_config(self.config)

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Sticky Panel Enabled\n\n"
                    "The FH ticket panel is now active."
                ),
                accent_colour=FH_BLUE
            )
        )

        await ctx.send(view=view)

    # ========================================================
    # DISABLE
    # ========================================================

    @stickypanel_cmd.command(
        name="disable"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def disable_panel(
        self,
        ctx
    ):
        self.config["enabled"] = False
        save_config(self.config)

        for task in self.pending.values():
            task.cancel()

        self.pending.clear()

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Sticky Panel Disabled\n\n"
                    "The FH ticket panel has been disabled."
                ),
                accent_colour=FH_BLUE
            )
        )

        await ctx.send(view=view)

    # ========================================================
    # PREVIEW
    # ========================================================

    @stickypanel_cmd.command(
        name="preview"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def panel_preview(
        self,
        ctx
    ):
        await ctx.send(
            view=self.build_panel_view(
                ctx.channel
            )
        )

    # ========================================================
    # REFRESH
    # ========================================================

    @stickypanel_cmd.command(
        name="refresh"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def refresh_panel(
        self,
        ctx
    ):
        if not self.config.get(
            "enabled",
            False
        ):
            return await ctx.send(
                "❌ The panel is disabled. "
                f"Use `{self.prefix}stickypanel enable` first."
            )

        if not await self.is_modmail_thread(
            ctx.channel
        ):
            return await ctx.send(
                "❌ Run this command inside a Modmail ticket."
            )

        self.schedule_resend(
            ctx.channel,
            delay=0
        )

        try:
            await ctx.message.add_reaction(
                "✅"
            )
        except discord.HTTPException:
            pass

    # ========================================================
    # TITLE
    # ========================================================

    @stickypanel_cmd.command(
        name="title"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def set_title(
        self,
        ctx,
        *,
        text: str
    ):
        text = text.strip()

        if len(text) > 256:
            return await ctx.send(
                "❌ Title can be 256 characters maximum."
            )

        self.config["title"] = text
        save_config(self.config)

        await ctx.send(
            f"✅ Panel title set to **{text}**."
        )

    # ========================================================
    # DESCRIPTION
    # ========================================================

    @stickypanel_cmd.command(
        name="description"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def set_description(
        self,
        ctx,
        *,
        text: str
    ):
        text = text.strip()

        if len(text) > 4000:
            return await ctx.send(
                "❌ Description can be 4000 characters maximum."
            )

        self.config["description"] = text
        save_config(self.config)

        await ctx.send(
            "✅ Panel description updated."
        )

    # ========================================================
    # DELAY
    # ========================================================

    @stickypanel_cmd.command(
        name="delay"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def set_delay(
        self,
        ctx,
        seconds: float
    ):
        if not 0 <= seconds <= 60:
            return await ctx.send(
                "❌ Delay must be between 0 and 60 seconds."
            )

        self.config["delay"] = seconds
        save_config(self.config)

        await ctx.send(
            f"✅ Panel delay set to `{seconds:g}s`."
        )

    # ========================================================
    # COLOR
    # ========================================================

    @stickypanel_cmd.command(
        name="color",
        aliases=["colour"]
    )
    @commands.has_permissions(
        administrator=True
    )
    async def set_color(
        self,
        ctx,
        hex_code: str
    ):
        try:
            value = int(
                hex_code.strip().lstrip("#"),
                16
            )

            if not 0 <= value <= 0xFFFFFF:
                raise ValueError

        except ValueError:
            return await ctx.send(
                "❌ Use a hex colour such as `#5865F2`."
            )

        self.config["color"] = value
        save_config(self.config)

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Panel Colour Updated\n\n"
                    f"New colour: `#{value:06X}`"
                ),
                accent_colour=value
            )
        )

        await ctx.send(view=view)

    # ========================================================
    # RESET
    # ========================================================

    @stickypanel_cmd.command(
        name="reset"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def reset_appearance(
        self,
        ctx
    ):
        for key in (
            "title",
            "description",
            "delay",
            "color"
        ):
            self.config[key] = (
                DEFAULT_CONFIG[key]
            )

        save_config(self.config)

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Appearance Reset\n\n"
                    f"**Title:** {DEFAULT_TITLE}\n"
                    f"**Delay:** `{DEFAULT_DELAY:g}s`\n"
                    f"**Colour:** `#{FH_BLUE:06X}`\n\n"
                    "Your buttons and categories were kept."
                ),
                accent_colour=FH_BLUE
            )
        )

        await ctx.send(view=view)

    # ========================================================
    # ADD BUTTON
    # ========================================================

    @stickypanel_cmd.command(
        name="addbutton"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def add_button(
        self,
        ctx
    ):
        button = discord.ui.Button(
            label="Configure Button",
            emoji="🔘",
            style=discord.ButtonStyle.primary
        )

        async def btn_callback(
            interaction
        ):
            await interaction.response.send_modal(
                AddButtonModal(self)
            )

        button.callback = btn_callback

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Add Action Button\n\n"
                    "Click the button below to configure "
                    "a new ticket action."
                ),
                make_separator(),
                make_action_row(button),
                accent_colour=FH_BLUE
            )
        )

        await ctx.send(view=view)

    # ========================================================
    # REMOVE BUTTON
    # ========================================================

    @stickypanel_cmd.command(
        name="removebutton"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def remove_button(
        self,
        ctx
    ):
        if not self.config["buttons"]:
            return await ctx.send(
                "❌ There are no buttons configured."
            )

        await ctx.send(
            view=RemoveButtonView(self)
        )

    # ========================================================
    # ADD CATEGORY
    # ========================================================

    @stickypanel_cmd.command(
        name="addcategory"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def add_category(
        self,
        ctx
    ):
        button = discord.ui.Button(
            label="Configure Category",
            emoji="📁",
            style=discord.ButtonStyle.primary
        )

        async def btn_callback(
            interaction
        ):
            await interaction.response.send_modal(
                AddCategoryModal(self)
            )

        button.callback = btn_callback

        view = discord.ui.LayoutView()

        view.add_item(
            discord.ui.Container(
                make_text(
                    "## FH Development\n"
                    "### Add Ticket Category\n\n"
                    "Click below to configure a category "
                    "for the ticket dropdown."
                ),
                make_separator(),
                make_action_row(button),
                accent_colour=FH_BLUE
            )
        )

        await ctx.send(view=view)

    # ========================================================
    # REMOVE CATEGORY
    # ========================================================

    @stickypanel_cmd.command(
        name="removecategory"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def remove_category(
        self,
        ctx
    ):
        if not self.config["categories"]:
            return await ctx.send(
                "❌ There are no categories configured."
            )

        await ctx.send(
            view=RemoveCategoryView(self)
        )

    # ========================================================
    # THREAD READY
    # ========================================================

    @commands.Cog.listener()
    async def on_thread_ready(
        self,
        thread,
        *args,
        **kwargs
    ):
        channel = getattr(
            thread,
            "channel",
            None
        )

        if channel:
            self.schedule_resend(
                channel,
                delay=2.0
            )

    # ========================================================
    # THREAD CLOSE
    # ========================================================

    @commands.Cog.listener()
    async def on_thread_close(
        self,
        thread,
        *args,
        **kwargs
    ):
        channel = getattr(
            thread,
            "channel",
            None
        )

        if not channel:
            return

        task = self.pending.pop(
            channel.id,
            None
        )

        if task:
            task.cancel()

        self.sticky_messages.pop(
            channel.id,
            None
        )

        self.locks.pop(
            channel.id,
            None
        )

    # ========================================================
    # MESSAGE LISTENER
    # ========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message
    ):
        if not self.config.get(
            "enabled",
            False
        ):
            return

        if not isinstance(
            message.channel,
            discord.TextChannel
        ):
            return

        # Only bot messages should move the panel.
        if not message.author.bot:
            return

        # Ignore our own panel.
        if self.is_panel_message(
            message
        ):
            return

        if not await self.is_modmail_thread(
            message.channel
        ):
            return

        self.schedule_resend(
            message.channel
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot):
    await bot.add_cog(
        StickyPanel(bot)
    )
