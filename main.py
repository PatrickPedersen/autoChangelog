import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

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
    input_changelog_file: Path = Path("CHANGELOG.md")
    input_changelog_title: str = "### Changelog"
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


class PartialGitHubEventInputs(BaseModel):
    number: int


class PartialGitHubEvent(BaseModel):
    number: Optional[int] = None
    inputs: Optional[PartialGitHubEventInputs] = None


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
    template_content = settings.input_template_file.read_text("utf-8")
    template = Template(template_content)
    message = template.render(issue=issue)
    if message in content:
        raise RuntimeError(
            f"Changelog entry already exists for issue: {issue.number}"
        )
    pre_header_content = content[: header_match.end()].strip()
    post_header_content = content[header_match.end() :].strip()
    next_release_match = re.search(
        settings.input_end_regex, post_header_content, flags=re.MULTILINE
    )
    release_end = (
        len(content)
        if not next_release_match
        else header_match.end() + next_release_match.start()
    )
    release_content = content[header_match.end() : release_end].strip()
    post_release_content = content[release_end:].strip()
    sections: list[SectionContent] = []
    sectionless_content = ""
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
            release_content[label_match.end() :],
            flags=re.MULTILINE,
        )
        label_section_end = (
            len(release_content)
            if not next_label_match
            else label_match.end() + next_label_match.start()
        )
        label_content = release_content[label_match.end() : label_section_end].strip()
        section = SectionContent(
            label=label.label,
            header=label.header,
            content=label_content,
            index=label_match.start(),
        )
        sections.append(section)
    sections.sort(key=lambda x: x.index)
    sections_keys = {section.label: section for section in sections}
    if not sections:
        sectionless_content = release_content
    elif sections[0].index > 0:
        sectionless_content = release_content[: sections[0].index].strip()
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
    if not found:
        if sectionless_content:
            sectionless_content = f"{message}\n{sectionless_content}"
        else:
            sectionless_content = f"{message}"
    new_release_content = ""
    if sectionless_content:
        new_release_content = f"{sectionless_content}"
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
    new_content = (
        f"{pre_header_content}\n\n{new_release_content}\n\n{post_release_content}".strip()
        + "\n"
    )
    return new_content


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
    subprocess.run(["git", "commit", "-m", "Update Changelog"], check=True)
    logging.info("Pushing changes")
    subprocess.run(["git", "push"], check=True)


def main() -> None:
    settings = Settings()
    if settings.input_debug_logs:
        logging.info("Settings: %s", settings.json())
    g = Github(settings.input_token.get_secret_value())
    repo = g.get_repo(settings.github_repository)
    if not settings.github_event_path.is_file():
        logging.error("Event file not found: %s", settings.github_event_path)
        sys.exit(1)
    contents = settings.github_event_path.read_text()
    event = PartialGitHubEvent.mode_validate_json(contents)
    if event.number is not None:
        number = event.number
    elif event.inputs and event.inputs.number:
        number = event.inputs.number
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
