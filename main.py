import os
from github import Github
from github.Issue import Issue


def main() -> None:
    print(os.getenv("GITHUB_CONTEXT"))
    # g = Github(os.getenv("GITHUB_TOKEN"))
    # repo = g.get_repo(os.getenv("GITHUB_REPOSITORY"))
    # number = int(os.getenv("GITHUB_ISSUE_NUMBER"))
    # issue: Issue = repo.get_issue(number)
    # print(issue.title)
    # g.close()
