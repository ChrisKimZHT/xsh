"""skills.py - 技能工具：按需载入工作区技能库中的 Markdown 指令包。"""

from pydantic import Field

from xsh.prompt import PromptSection
from xsh.skills import SkillLibrary
from xsh.tools.base import Tool, ToolArgs

_SKILL_GUIDANCE = (
    "Use the skill tool to load a named skill (a reusable Markdown instruction pack) when its "
    "topic is relevant to the task. Available skills are listed in the system prompt; call the "
    "tool without a name to list them again. Loaded skill text is guidance to follow, not user "
    "input."
)


class SkillArgs(ToolArgs):
    name: str = Field(default="", description="Skill name to load; omit to list available skills.")


class SkillTools:
    def __init__(self, library: SkillLibrary):
        self.library = library

    def run(self, args: SkillArgs) -> str:
        name = args.name.strip()
        if not name:
            index = self.library.render_index()
            return "Available skills:\n" + (index or "(none)")
        content = self.library.read(name)
        return f"Skill: {name}\n\n{content}"

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "skill",
                "Load a named workspace skill (reusable Markdown instructions) on demand.",
                SkillArgs,
                self.run,
                guidance=_SKILL_GUIDANCE,
                prompt_sections=(PromptSection("tool:skill", 300, _SKILL_GUIDANCE),),
            ),
        ]
