# Profile stats workflow

## October 7 investigation

The first failing scheduled run was October 1, 2026. It and the October 7 run stopped in `user_getter` with HTTP 401 `Bad credentials`. The September 30 run succeeded. These failures predate the animated SVG commit. The API does not identify whether the old personal token expired, was revoked, or was replaced incorrectly; only rejection is confirmed.

Repository workflow permissions already allowed writing. Checkout and dependency installation succeeded. The failing request used the custom `ACCESS_TOKEN` secret, not the checkout/push credential.

## Repair

- Use the job-scoped `github.token` for public API queries and repository updates. No personal-token renewal or extra secret is required.
- Explicit `contents: write`, serialized runs, a fifteen-minute timeout, and narrow staging of generated output.
- Pin checkout v7.0.1 and setup-python v7.0.0 to verified release commit SHAs. Use setup-python's pip cache instead of a separate cache action.
- Pin Python dependencies to the versions used during testing.
- Schedule at 04:17 UTC daily rather than the busy hour boundary (09:47 in India). Scheduled starts can be delayed by GitHub.
- Fetch only public repositories. Private repositories inaccessible to the job token are intentionally excluded rather than silently mixing scopes.
- Paginate repository and authored-commit history connections fully.
- Query each history at an immutable head SHA, so concurrent changes do not mix snapshots.
- Key the cache by repository identity and head SHA, not list position or commit count. An equal-count force push invalidates the cache.
- Handle empty repositories, stale/corrupt caches, HTTP 200 GraphQL errors, bounded transient retries, and request timeouts.
- Validate both SVGs before writing; atomically replace each generated file. Preserve motion, coordinates, and stat IDs.
- Check the latest main branch and rebase before pushing rather than overwriting concurrent work.

## Metric definitions

`Repos`: owned public repositories, including forks. `Stars`: stars on those owned repositories, not repositories starred by the account. `Contributed`: public repositories returned by the owner's existing OWNER/COLLABORATOR/ORGANIZATION_MEMBER affiliation selection; this is not a lifetime contribution count. `Commits`: commits authored by the account reachable from the selected default-branch heads. `Lines of Code`: authored additions minus deletions, not a source-tree line census.

## Validation

Run `python -m unittest discover -s tests -p test_today.py -v` (17 regression tests). The tests cover authentication and GraphQL failures, timeout/retry behavior, pagination, empty repositories, immutable heads, cache invalidation/order/removal, malformed caches, atomic writes, and SVG animation preservation.

A local live API check writes into a temporary directory via `today.py --output-dir PATH` without changing the profile assets. An actual successful Actions run is required to confirm the job token, hosted runner, and push permissions end to end.
