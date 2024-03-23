from github import Github
from github.Issue import Issue


def main() -> None:
    g = Github("access_token")
    repo = g.get_repo("owner/repo")
    issue: Issue = repo.get_issue(1)
    print(issue.title)
