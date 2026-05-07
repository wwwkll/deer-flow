"""Subagent registry for managing available subagents."""

import logging
from dataclasses import replace
from pathlib import Path

import yaml

from deerflow.sandbox.security import is_host_bash_allowed
from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
from deerflow.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)

_SUBAGENT_CONFIG_FIELDS = {
    "description",
    "tools",
    "disallowed_tools",
    "skills",
    "model",
    "max_turns",
    "timeout_seconds",
}


def _build_custom_subagent_config(name: str) -> SubagentConfig | None:
    """Build a SubagentConfig from config.yaml custom_agents section.

    Args:
        name: The name of the custom subagent.

    Returns:
        SubagentConfig if found in custom_agents, None otherwise.
    """
    from deerflow.config.subagents_config import get_subagents_app_config

    app_config = get_subagents_app_config()
    custom = app_config.custom_agents.get(name)
    if custom is None:
        return None

    return SubagentConfig(
        name=name,
        description=custom.description,
        system_prompt=custom.system_prompt,
        tools=custom.tools,
        disallowed_tools=custom.disallowed_tools,
        skills=custom.skills,
        model=custom.model,
        max_turns=custom.max_turns,
        timeout_seconds=custom.timeout_seconds,
    )


def _build_subagent_from_agents_dir(name: str) -> SubagentConfig | None:
    """Build a SubagentConfig from backend/.deer-flow/agents/{name}/ directory.

    Reads config.yaml for metadata (tools, model, etc.) and SOUL.md for
    system_prompt. This provides a file-based alternative to the config.yaml
    custom_agents section, keeping prompts and code separate.

    Args:
        name: The name of the custom subagent.

    Returns:
        SubagentConfig if the agent directory and required files exist, None otherwise.
    """
    from deerflow.config.paths import get_paths

    agent_dir = get_paths().agent_dir(name)
    if not agent_dir.exists():
        return None

    soul_path = agent_dir / "SOUL.md"
    if not soul_path.exists():
        return None

    system_prompt = soul_path.read_text(encoding="utf-8").strip()
    if not system_prompt:
        return None

    config_path = agent_dir / "config.yaml"
    meta: dict = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Failed to parse subagent config %s: %s", config_path, e)

    description = meta.pop("description", "")
    fields = {k: v for k, v in meta.items() if k in _SUBAGENT_CONFIG_FIELDS}

    return SubagentConfig(
        name=name,
        description=description,
        system_prompt=system_prompt,
        **fields,
    )


def get_subagent_config(name: str) -> SubagentConfig | None:
    """Get a subagent configuration by name, with config.yaml overrides applied.

    Resolution order (mirrors Codex's config layering):
    1. Built-in subagents (general-purpose, bash)
    2. Custom subagents from config.yaml custom_agents section
    3. Per-agent overrides from config.yaml agents section (timeout, max_turns, model, skills)

    Args:
        name: The name of the subagent.

    Returns:
        SubagentConfig if found (with any config.yaml overrides applied), None otherwise.
    """
    # Step 1: Look up built-in, then custom_agents, then agents directory
    config = BUILTIN_SUBAGENTS.get(name)
    if config is None:
        config = _build_custom_subagent_config(name)
    if config is None:
        config = _build_subagent_from_agents_dir(name)
    if config is None:
        return None

    # Step 2: Apply per-agent overrides from config.yaml agents section.
    # Only explicit per-agent overrides are applied here. Global defaults
    # (timeout_seconds, max_turns at the top level) apply to built-in agents
    # but must NOT override custom agents' own values — custom agents define
    # their own defaults in the custom_agents section.
    # Lazy import to avoid circular deps.
    from deerflow.config.subagents_config import get_subagents_app_config

    app_config = get_subagents_app_config()
    is_builtin = name in BUILTIN_SUBAGENTS
    agent_override = app_config.agents.get(name)

    overrides = {}

    # Timeout: per-agent override > global default (builtins only) > config's own value
    if agent_override is not None and agent_override.timeout_seconds is not None:
        if agent_override.timeout_seconds != config.timeout_seconds:
            logger.debug("Subagent '%s': timeout overridden (%ss -> %ss)", name, config.timeout_seconds, agent_override.timeout_seconds)
            overrides["timeout_seconds"] = agent_override.timeout_seconds
    elif is_builtin and app_config.timeout_seconds != config.timeout_seconds:
        logger.debug("Subagent '%s': timeout from global default (%ss -> %ss)", name, config.timeout_seconds, app_config.timeout_seconds)
        overrides["timeout_seconds"] = app_config.timeout_seconds

    # Max turns: per-agent override > global default (builtins only) > config's own value
    if agent_override is not None and agent_override.max_turns is not None:
        if agent_override.max_turns != config.max_turns:
            logger.debug("Subagent '%s': max_turns overridden (%s -> %s)", name, config.max_turns, agent_override.max_turns)
            overrides["max_turns"] = agent_override.max_turns
    elif is_builtin and app_config.max_turns is not None and app_config.max_turns != config.max_turns:
        logger.debug("Subagent '%s': max_turns from global default (%s -> %s)", name, config.max_turns, app_config.max_turns)
        overrides["max_turns"] = app_config.max_turns

    # Model: per-agent override only (no global default for model)
    effective_model = app_config.get_model_for(name)
    if effective_model is not None and effective_model != config.model:
        logger.debug("Subagent '%s': model overridden (%s -> %s)", name, config.model, effective_model)
        overrides["model"] = effective_model

    # Skills: per-agent override only (no global default for skills)
    effective_skills = app_config.get_skills_for(name)
    if effective_skills is not None and effective_skills != config.skills:
        logger.debug("Subagent '%s': skills overridden (%s -> %s)", name, config.skills, effective_skills)
        overrides["skills"] = effective_skills

    if overrides:
        config = replace(config, **overrides)

    return config


def list_subagents() -> list[SubagentConfig]:
    """List all available subagent configurations (with config.yaml overrides applied).

    Returns:
        List of all registered SubagentConfig instances (built-in + custom).
    """
    configs = []
    for name in get_subagent_names():
        config = get_subagent_config(name)
        if config is not None:
            configs.append(config)
    return configs


def get_subagent_names() -> list[str]:
    """Get all available subagent names (built-in + custom + agents directory).

    Returns:
        List of subagent names.
    """
    names = list(BUILTIN_SUBAGENTS.keys())

    # Merge custom_agents from config.yaml
    from deerflow.config.subagents_config import get_subagents_app_config

    app_config = get_subagents_app_config()
    for custom_name in app_config.custom_agents:
        if custom_name not in names:
            names.append(custom_name)

    # Merge agents from backend/.deer-flow/agents/ directory
    from deerflow.config.paths import get_paths

    agents_dir = get_paths().agents_dir
    if agents_dir.exists():
        for entry in agents_dir.iterdir():
            if entry.is_dir() and (entry / "SOUL.md").exists():
                agent_name = entry.name
                if agent_name not in names:
                    names.append(agent_name)

    return names


def get_available_subagent_names() -> list[str]:
    """Get subagent names that should be exposed to the active runtime.

    Returns:
        List of subagent names visible to the current sandbox configuration.
    """
    names = get_subagent_names()
    try:
        host_bash_allowed = is_host_bash_allowed()
    except Exception:
        logger.debug("Could not determine host bash availability; exposing all subagents")
        return names

    if not host_bash_allowed:
        names = [name for name in names if name != "bash"]
    return names
