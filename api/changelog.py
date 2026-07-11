"""Dashboard version history, shown at /changelog and in the footer."""

from dataclasses import dataclass


@dataclass
class ChangelogEntry:
    version: str
    date: str
    summary: list[str]


CURRENT_VERSION = "1.2.0"

CHANGELOG: list[ChangelogEntry] = [
    ChangelogEntry(
        version="1.2.0",
        date="2026-07-11",
        summary=[
            "Full redesign: black background, Nova-260 mascot logo, table-style link list",
            "Site and generated content (descriptions, Q&A, digests) switched to English",
            "Split navigation into Links / Daily digest / Weekly digest",
            "Removed search/chat filters and the similar-links feature; unified button styles",
            "Added this changelog page",
        ],
    ),
    ChangelogEntry(
        version="1.1.0",
        date="2026-07-10",
        summary=[
            "Click-based popularity metric replacing internal counters",
            "Daily top-3 picks collection, unified record editing, similar-links feature",
            "Invite-code self-service authorization for the bot",
        ],
    ),
    ChangelogEntry(
        version="1.0.0",
        date="2026-07-09",
        summary=[
            "Initial release: bot, worker pipeline, dashboard, RAG Q&A, research reports",
        ],
    ),
]
