# Provider capability map

`available` in `x_status` means a configured route exists. `validation` independently
reports whether a successful real request has been recorded by this instance.
Offline fixture tests do not make a deployed instance appear live-verified.

| View | FxTwitter v2 route | Session raw adapter | Live evidence on 2026-09-16 |
|---|---|---|---|
| post | `/2/status/{id}` | `tweet_details_raw` | Free API success |
| thread | `/2/thread/{id}` | `tweet_thread_raw` | Free API success |
| replies | `/2/conversation/{id}` | `tweet_replies_raw` | Free API success; session returns direct replies |
| quotes | `/2/status/{id}/quotes` | `search_raw(quoted_tweet_id:...)` | Not live-verified |
| reposters | `/2/status/{id}/reposts` | `retweeters_raw` | Not live-verified |
| profile | `/2/profile/{handle}` | `user_by_login_raw` | Free API success |
| user posts / with replies | `/2/profile/{handle}/statuses` | `user_tweets_raw` / `user_tweets_and_replies_raw` | Posts success |
| media / articles | `/2/profile/{handle}/media`, `/articles` | `user_media_raw`; no session articles | Not live-verified |
| followers / following | `/2/profile/{handle}/followers`, `/following` | `followers_raw` / `following_raw` | Not live-verified |
| search posts / users | `/2/search`, `/2/typeahead?result_type=users` | `search_raw` with product selection | Post search degraded (ambiguous 404); user suggestions succeeded |
| list posts / members | None | `list_timeline_raw` / `list_members_raw` | Session unverified; explicit public marker required |
| community info / posts / members | None | `community_info_raw`, `community_tweets_raw`, `community_members_raw` | Session unverified; explicit public marker required |
| trending | `/2/trends` | `trends_raw` | Free API success |
| news / sport / entertainment trends | None | `trends_raw` categories | Session unverified |

Free search has a documented route but was not usable in the recorded smoke
test. Anonymous route failures can be geographic, temporary or source changes.
No live owner session was available during implementation. We do not advertise
unverified adapters as successful account tests.

In particular, upstream list/community responses may omit public visibility.
Those requests return `PUBLIC_UNVERIFIED` until the upstream response contains
an explicit supported marker. This gate is intentional and is not bypassed by
guessing from a URL or an open join policy.

The source can ignore requested count: a request for three user posts returned
twenty. The MCP service retains the remainder and enforces its own output budget.
Provider ordering, ranking and coverage differ; a fallback is disclosed and is
not applied in the middle of a pagination sequence.

Free user search provides typeahead suggestions, with no upstream pagination.
Session user search uses X's People search. Session replies expose direct replies
in the source's default ranking; their warning explicitly says the requested
sort is not guaranteed. FxTwitter replies support recency/likes ranking.
Articles retain available title, preview, text blocks and markdown in full mode;
use `x_result_get(field="json")` when the normalized article exceeds the budget.
