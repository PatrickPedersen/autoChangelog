import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union, Any

from github import Github
from github.Issue import Issue
from jinja2 import Template
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings


class Section(BaseModel):
    label: str
    header: str


class Settings(BaseSettings):
    github_repository: str
    github_event_path: Path
    github_event_name: Optional[str] = None
    input_token: SecretStr
    input_changelog_file: Path = Path("README.md")
    input_changelog_title: str = "### Latest Changes"
    input_template_file: Path = Path(__file__).parent / "templates/changelog.jinja2"
    input_end_regex: str = "(^### .*)|(^## .*)"
    input_debug_logs: Optional[bool] = False
    input_labels: List[Section] = [
        Section(label="breaking", header="Breaking Changes"),
        Section(label="security", header="Security Fixes"),
        Section(label="feature", header="Features"),
        Section(label="bug", header="Fixes"),
        Section(label="refactor", header="Refactors"),
        Section(label="upgrade", header="Upgrades"),
        Section(label="docs", header="Docs"),
        Section(label="lang-all", header="Translations"),
        Section(label="internal", header="Internal"),
    ]
    input_label_header_prefix: str = "#### "


class PartialGitHubIssue(BaseModel):
    number: Optional[int] = None


class PartialGitHubEvent(BaseModel):
    issue: Optional[PartialGitHubIssue] = None


class TemplateDataUser(BaseModel):
    login: str
    html_url: str


class TemplateDataIssue(BaseModel):
    number: int
    title: str
    html_url: str
    user: TemplateDataUser


class SectionContent(BaseModel):
    label: str
    header: str
    content: str
    index: int


logging.basicConfig(level=logging.INFO)


def generate_markdown_content(
        *,
        content: str,
        settings: Settings,
        issue: Union[Issue, TemplateDataIssue],
        labels: list[str]
) -> str:
    header_match = re.search(
        settings.input_changelog_title, content, flags=re.MULTILINE
    )
    if not header_match:
        raise RuntimeError(
            f"Changelog title not found in {settings.input_changelog_file}"
        )
    message = Template(settings.input_template_file.read_text("utf-8")).render(issue=issue)
    if message in content:
        raise RuntimeError(
            f"Changelog entry already exists for issue: {issue.number}"
        )
    next_release_match = re.search(
        settings.input_end_regex, content[header_match.end():].strip(), flags=re.MULTILINE
    )
    release_end = (
        len(content)
        if not next_release_match
        else header_match.end() + next_release_match.start()
    )
    release_content = content[header_match.end(): release_end].strip()
    section_less_content, new_sections = get_release_content(release_content, labels, message, settings)
    new_release_content = get_new_release_content(section_less_content, new_sections, settings)
    pre_header_content = content[: header_match.end()].strip()
    post_release_content = content[release_end:].strip()
    new_content = (
            f"{pre_header_content}\n\n{new_release_content}\n\n{post_release_content}".strip()
            + "\n"
    )
    return new_content


def get_sections(release_content: str, settings: Settings) -> list[SectionContent]:
    sections: list[SectionContent] = []
    for label in settings.input_labels:
        label_match = re.search(
            f"^{settings.input_label_header_prefix}{label.header}",
            release_content,
            flags=re.MULTILINE
        )
        if not label_match:
            continue
        next_label_match = re.search(
            f"^{settings.input_label_header_prefix}",
            release_content[label_match.end():],
            flags=re.MULTILINE,
        )
        label_section_end = (
            len(release_content)
            if not next_label_match
            else label_match.end() + next_label_match.start()
        )
        label_content = release_content[label_match.end(): label_section_end].strip()
        section = SectionContent(
            label=label.label,
            header=label.header,
            content=label_content,
            index=label_match.start(),
        )
        sections.append(section)
    sections.sort(key=lambda x: x.index)
    return sections


def get_new_sections(sections_keys, labels, message, settings: Settings) -> tuple[list[SectionContent], bool, Any]:
    new_sections: list[SectionContent] = []
    found = False
    for label in settings.input_labels:
        if label.label in sections_keys:
            section = sections_keys[label.label]
        else:
            section = SectionContent(
                label=label.label,
                header=label.header,
                content="",
                index=-1,
            )
            sections_keys[label.label] = section
        if label.label in labels and not found:
            found = True
            section.content = f"{message}\n{section.content}".strip()
        new_sections.append(section)
    return new_sections, found, message


def get_new_release_content(section_less_content, new_sections, settings: Settings) -> str:
    new_release_content = ""
    if section_less_content:
        new_release_content = f"{section_less_content}"
    use_sections = [
        f"{settings.input_label_header_prefix}{section.header}\n\n{section.content}"
        for section in new_sections
        if section.content
    ]
    updated_content = "\n\n".join(use_sections)
    if new_release_content:
        if updated_content:
            new_release_content += f"\n\n{updated_content}"
    else:
        new_release_content = updated_content
    return new_release_content


def get_release_content(
        release_content: str,
        labels,
        message,
        settings: Settings
) -> tuple[str, list[SectionContent]]:
    sections = get_sections(release_content, settings)
    sections_keys = {section.label: section for section in sections}
    section_less_content = ""
    if not sections:
        section_less_content = release_content
    elif sections[0].index > 0:
        section_less_content = release_content[: sections[0].index].strip()
    new_sections, found, message = get_new_sections(sections_keys, labels, message, settings)
    if not found:
        if section_less_content:
            section_less_content = f"{message}\n{section_less_content}"
        else:
            section_less_content = f"{message}"
    return section_less_content, new_sections


def setup_gituser() -> None:
    logging.info("Setting up GitHub Actions git user")
    subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions@github.com"], check=True)


def update_changelog(settings, issue) -> None:
    logging.info("Updating Changelog")
    logging.info("Pulling latest changes")
    subprocess.run(["git", "pull"], check=True)
    content = settings.input_changelog_file.read_text()
    new_content = generate_markdown_content(
        content=content,
        settings=settings,
        issue=issue,
        labels=[label.name for label in issue.labels],
    )
    settings.input_changelog_file.write_text(new_content)
    logging.info("Committing changes to: %s", settings.input_changelog_file)
    subprocess.run(["git", "add", str(settings.input_changelog_file)], check=True)
    subprocess.run(["git", "commit", "-m", "[CI] Update Changelog"], check=True)
    logging.info("Pushing changes")
    subprocess.run(["git", "push"], check=True)


def main() -> None:
    # Ref: https://github.com/actions/runner/issues/2033
    logging.info(
        "GitHub Actions workaround for git in containers, ref: https://github.com/actions/runner/issues/2033"
    )
    safe_directory_config_content = "[safe]\n\tdirectory = /github/workspace"
    dotgitconfig_path = Path.home() / ".gitconfig"
    dotgitconfig_path.write_text(safe_directory_config_content)
    settings = Settings()
    if settings.input_debug_logs:
        logging.info("Settings: %s", settings.json())
    g = Github(settings.input_token.get_secret_value())
    repo = g.get_repo(settings.github_repository)
    if not settings.github_event_path.is_file():
        logging.error("Event file not found: %s", settings.github_event_path)
        sys.exit(1)
    contents = settings.github_event_path.read_text()
    event = PartialGitHubEvent.model_validate_json(contents)
    if event.issue.number is not None:
        number = event.issue.number
    else:
        logging.error("No Issue number was found in the event file at: %s", settings.github_event_path)
        sys.exit(1)
    issue: Issue = repo.get_issue(number)
    if issue.state != "closed":
        logging.error("Issue #%s is not closed", number)
        sys.exit(0)
    if not settings.input_changelog_file.is_file():
        logging.error("Changelog file not found: %s", settings.input_changelog_file)
        sys.exit(1)
    setup_gituser()
    update_changelog(settings, issue)
    logging.info("Changelog updated successfully")
