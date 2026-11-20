# Build and publish the documentation

Use the MkDocs preview to review changes to the public docs. Before you begin, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and open a terminal in the checkout root.

## Build locally

Start the live preview with the pinned documentation requirements.

```sh
uv run --no-project --python 3.12 --with-requirements docs/requirements.txt mkdocs serve --dev-addr 127.0.0.1:8001
```

Open [the local preview](http://127.0.0.1:8001/) and check the pages you changed. In another terminal, run the same strict build that GitHub Actions runs.

```sh
uv run --no-project --python 3.12 --with-requirements docs/requirements.txt mkdocs build --strict
```

The build writes HTML to `site/` and fails on warnings about the navigation, relative links, or anchors.

## What to publish

Add public pages to the navigation in `mkdocs.yml`. When you move a section from an existing page, keep its old anchor and link to the new location. This keeps existing bookmarks and inbound links working.

Use synthetic fixtures in examples and run each changed command from the working directory stated in the guide. For language or behavior changes, update the affected reference alongside the code. Publish the grammar and typed strategy schema with the [language reference](language-spec.md).

Check your staged files before pushing. Use private storage for internal notes, credentials, and real user data. Review any run bundles before sharing them because they include the submitted strategy and candles.

## Publish to Read the Docs

1. Open or update a pull request targeting `main`. Wait for GitHub Actions and the Read the Docs check on the latest commit.
2. Open the Read the Docs preview from the check. Follow the affected user paths and check page links, moved section anchors, and any example downloads.
3. After the pull request merges, open [Build history](https://app.readthedocs.org/projects/tradelang/builds/) and confirm that `latest` built from the merge commit. Open [the published docs](https://tradelang.readthedocs.io/en/latest/) and verify the changed pages.

For a tagged release, check the corresponding documentation build and the `stable` version. See [Read the Docs versioning](https://docs.readthedocs.com/platform/stable/versions.html).
