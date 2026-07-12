"""Dashboard version history, shown at /changelog and in the footer."""

from dataclasses import dataclass


@dataclass
class ChangelogEntry:
    version: str
    date: str
    summary: list[str]


CURRENT_VERSION = "2.1.2"

# date: "YYYY-MM-DD HH:MM" — несколько релизов за день не редкость, время
# нужно, чтобы порядок и дата были действительно проверяемы (см. git log),
# а не проставлены на глаз задним числом.
CHANGELOG: list[ChangelogEntry] = [
    ChangelogEntry(
        version="2.1.2",
        date="2026-07-12 20:10",
        summary=[
            "Voice DNA: replaced the single guessed \"confidence\" score with "
            "two numbers computed directly from the per-post data — style "
            "consistency and structure consistency",
            "The report's headline voice description now comes from one "
            "source instead of two separately-generated ones that could "
            "quietly disagree",
            "Report prompts now stop the model from writing that a voice is "
            "\"undetermined\" when the computed consistency is actually high",
        ],
    ),
    ChangelogEntry(
        version="2.1.1",
        date="2026-07-12 18:55",
        summary=[
            "Fixed a bug where Voice DNA reports could fail during the "
            "final write-up step",
            "Channel Parser progress screen: swapped the mini-game for a "
            "snake game with a live score, still paced by real scrape "
            "progress",
            "Group chats: Posts now only captures messages with an "
            "external link (forwarded channel posts sent directly to the "
            "bot are unaffected)",
            "Posts table: date is now its own column, and the Post column "
            "always shows the source channel's name — including for "
            "channel posts forwarded into a DM",
        ],
    ),
    ChangelogEntry(
        version="2.1.0",
        date="2026-07-12 17:20",
        summary=[
            "Channels tab now opens on a history page — every channel "
            "you've parsed, with status, post count, and quick links to "
            "its results table and Voice DNA report",
            "Channel Parser is feature-complete: wizard, results table, "
            "CSV/MD export, and Voice DNA reports all shipped",
        ],
    ),
    ChangelogEntry(
        version="2.0.0",
        date="2026-07-12 17:05",
        summary=[
            "Voice DNA report — a full stylometric + AI-written analysis of a "
            "parsed channel's writing style: tone, structure, rhetoric, and "
            "engagement patterns, laid out across four tabs (Summary, "
            "Structure, Content, Insights) with 13 charts",
            "Voice DNA reports can be downloaded as markdown",
        ],
    ),
    ChangelogEntry(
        version="1.9.0",
        date="2026-07-12 13:44",
        summary=[
            "Channel Parser step 3: a results table for every parsed "
            "channel — date, preview, views, reactions, comments — "
            "sortable and with a one-click post preview popup",
            "Download a channel's parsed posts as .csv or .md",
        ],
    ),
    ChangelogEntry(
        version="1.8.0",
        date="2026-07-12 13:31",
        summary=[
            "New \"Channels\" tab — parse an entire public Telegram channel "
            "instead of one post at a time: enter a @username, pick a post "
            "limit and filters, and a background job scrapes the channel's "
            "public feed",
            "Live progress page while a channel parses, with a small canvas "
            "mini-game that races along with the real scrape progress",
        ],
    ),
    ChangelogEntry(
        version="1.7.0",
        date="2026-07-12 15:31",
        summary=[
            "Links table: titles now truncate cleanly with an ellipsis "
            "instead of wrapping to a different number of lines per row — "
            "rows are finally even",
            "Priority and Tested are now editable right in the table — a "
            "dropdown and a checkbox that save instantly, no need to open "
            "Edit; \"Post\" column renamed to \"Post Link\"",
            "Added a \"By usefulness\" sort (highest first)",
            "Daily digest and Weekly digest merged into one \"Digest\" tab — "
            "a single feed tagged Daily/Weekly per entry instead of two "
            "separate pages; old links redirect automatically",
        ],
    ),
    ChangelogEntry(
        version="1.6.1",
        date="2026-07-12 15:09",
        summary=[
            "Links table: Description is now exactly 4x wider than Title "
            "(was barely noticeable), and titles wrap at word boundaries "
            "instead of butchering mid-word",
            "Action buttons (View/Edit/Hide) now stack vertically instead "
            "of running in a row",
            "Fixed the filter dropdown arrow and the \"+\" in Add link/Add "
            "post — both were sitting slightly off-center",
        ],
    ),
    ChangelogEntry(
        version="1.6.0",
        date="2026-07-12 14:45",
        summary=[
            "Links table reworked: Description is now the widest column, "
            "Date got its own column, and the click counter was dropped from "
            "the row — Usefulness moved before Actions so the action buttons "
            "are always the rightmost column",
            "Added a manual Priority (Low/Normal/High) and a Tested checkbox "
            "on every link, editable from the edit form; sort options are "
            "now Priority/Date/Tested with Date as the default",
            "Links page got a title and subtitle like Posts; \"+ Add link\" "
            "now opens leftward so it no longer runs off the page edge; "
            "pagination switched from a page-number list to arrows + \"Page "
            "X of Y\"",
            "The header search box now has a visible submit button — no "
            "more guessing that Enter is the only way to search",
            "The daily digest now broadcasts to the team in DM as soon as "
            "it's generated, the same way the weekly digest already did",
        ],
    ),
    ChangelogEntry(
        version="1.5.0",
        date="2026-07-11 22:16",
        summary=[
            "Posts: sort dropdown now matches the site's filter styling, the "
            "thumbnail was dropped from the title column, and posts can be "
            "hidden from the list just like links",
            "Manual \"+ Add post\" from the dashboard — paste a public t.me "
            "post link and it's fetched, classified, and added; the popover "
            "opens leftward so it no longer overflows the page edge",
            "Unified search: /ask now retrieves from both Links and Posts "
            "(posts got embeddings too) — the search box moved out of the "
            "Links page and into the center of the top nav, available "
            "everywhere",
            "Bot DMs: a post forwarded together with a link now gets a single "
            "combined confirmation instead of two separate messages; dropped "
            "the odd-sounding \"first in the base\" line in favor of a plain "
            "checkmark status with what was added and its tags",
        ],
    ),
    ChangelogEntry(
        version="1.4.2",
        date="2026-07-11 21:41",
        summary=[
            "Posts table now has the same filters as Links: tag dropdown and "
            "sort by priority/date (priority uses the same recency-decay "
            "formula, recomputed daily)",
            "The bot now confirms in DM whether a forwarded post was saved, "
            "was already in the base, or failed with an error",
        ],
    ),
    ChangelogEntry(
        version="1.4.1",
        date="2026-07-11 20:36",
        summary=[
            "Fixed inline buttons answering \"no access\" to everyone: the "
            "whitelist check was reading callback.message.from_user (the bot "
            "itself, author of the message the button is attached to) instead "
            "of callback.from_user (the person who actually clicked)",
        ],
    ),
    ChangelogEntry(
        version="1.4.0",
        date="2026-07-11 20:27",
        summary=[
            "Fixed inline bot buttons never firing at all — the webhook was only "
            "subscribed to message updates, so Telegram silently dropped "
            "every button press (callback_query)",
            "Links now have an Area (ai / design / coding / tech / business / "
            "other), classified by GPT alongside tags; filterable on the index",
            "Links index rebuilt as a real table: Title / Description / Tags / "
            "Area columns instead of a card feed",
            "Added manual link entry from the dashboard (+ Add link)",
            "New Posts tab: every group chat message is captured, with or "
            "without links — GPT summary, area, and tags; forwarded posts from "
            "public channels link to the original post so Telegram can preview it",
        ],
    ),
    ChangelogEntry(
        version="1.3.0",
        date="2026-07-11 16:05",
        summary=[
            "Daily/weekly digest rebuilt: GPT ranks the team's recent links by topic, "
            "then live-searches the web for freshly published articles matching that "
            "quality bar and picks a top 10 (kept in the digest only, not added to Links)",
            "Digest pages now show a date-titled list with an Actual badge for today's "
            "entry and open into a dedicated page per digest (title, link, description)",
            "Research reports: links inside the report text are now clickable, and "
            "reports can be downloaded as a .md file",
            "Footer version link is now visibly clickable (underlined accent color)",
        ],
    ),
    ChangelogEntry(
        version="1.2.0",
        date="2026-07-11 15:32",
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
        date="2026-07-10 18:33",
        summary=[
            "Click-based popularity metric replacing internal counters",
            "Daily top-3 picks collection, unified record editing, similar-links feature",
            "Invite-code self-service authorization for the bot",
        ],
    ),
    ChangelogEntry(
        version="1.0.0",
        date="2026-07-10 15:02",
        summary=[
            "Initial release: bot, worker pipeline, dashboard, RAG Q&A, research reports",
        ],
    ),
]
