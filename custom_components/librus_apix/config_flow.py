"""Config flow for Librus APIX integration."""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from librus_apix.client import new_client

from .const import DOMAIN
from .ai_prompts import (
    DEFAULT_PROMPT_WEEKLY_PARENT,
    DEFAULT_PROMPT_WEEKLY_STUDENT,
    DEFAULT_PROMPT_MESSAGES_PARENT,
    DEFAULT_PROMPT_MESSAGES_STUDENT,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict):
    """Validate the user input allows us to connect."""
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    
    # Test authentication
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        client = await loop.run_in_executor(None, new_client)
        token = await loop.run_in_executor(None, client.get_token, username, password)
        
        if not token:
            raise ValueError("Authentication failed")
            
        return {"title": f"Librus APIX ({username})"}
    
    except Exception as ex:
        _LOGGER.error("Authentication error: %s", ex)
        raise ValueError("Cannot connect") from ex


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Librus APIX."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", 
            data_schema=STEP_USER_DATA_SCHEMA, 
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return LibrusApixOptionsFlowHandler(config_entry)


class LibrusApixOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Librus APIX."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Manage general options."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_ai()

        schema = vol.Schema(
            {
                vol.Optional(
                    "fetch_messages_count",
                    default=self.entry.options.get("fetch_messages_count", 10),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=25)),
                vol.Optional(
                    "fetch_messages_content",
                    default=self.entry.options.get("fetch_messages_content", False),
                ): bool,
                vol.Optional(
                    "days_before_exam_study",
                    default=self.entry.options.get("days_before_exam_study", 2),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=7)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            last_step=False,
        )

    async def async_step_ai(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Manage AI options."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        schema = vol.Schema(
            {
                vol.Optional(
                    "ai_summary_enabled",
                    default=self.entry.options.get("ai_summary_enabled", False),
                ): bool,
                vol.Optional(
                    "ai_agent_id",
                    default=self.entry.options.get("ai_agent_id", "conversation.home_assistant"),
                ): str,
                vol.Optional(
                    "ai_prompt_messages_parent",
                    default=self.entry.options.get("ai_prompt_messages_parent", DEFAULT_PROMPT_MESSAGES_PARENT),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(
                    "ai_prompt_messages_student",
                    default=self.entry.options.get("ai_prompt_messages_student", DEFAULT_PROMPT_MESSAGES_STUDENT),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(
                    "ai_prompt_weekly_parent",
                    default=self.entry.options.get("ai_prompt_weekly_parent", DEFAULT_PROMPT_WEEKLY_PARENT),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(
                    "ai_prompt_weekly_student",
                    default=self.entry.options.get("ai_prompt_weekly_student", DEFAULT_PROMPT_WEEKLY_STUDENT),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )

        return self.async_show_form(
            step_id="ai",
            data_schema=schema,
        )