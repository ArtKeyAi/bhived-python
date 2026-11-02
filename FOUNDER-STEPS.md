# Founder steps: from this folder to a LangChain listing

Everything in this repo is built and tested locally. Nothing has been pushed, published or filed. These are the steps only you can do, in order. Each one depends on the one before it.

Checked on 2026-11-02: the PyPI names `bhived` and `langchain-bhived` are free, and `ArtKeyAi/bhived-python` doesn't exist on GitHub yet.

## 1. Look it over (5 min, optional)

```bash
cd C:\Users\Yossuf\Desktop\bhived\bhived-python
.venv\Scripts\python -m pytest
.venv\Scripts\python examples\offline_demo.py
```

Expect `92 passed, 1 skipped` (the skipped one is the optional live test). The demo prints the prompt block the model sees.

If you want to try it against the real API with your own key, this runs one read-only query and never writes:

```bash
set BHIVED_LIVE_SMOKE=1
.venv\Scripts\python -m pytest packages\bhived\tests\test_live_smoke.py
```

## 2. Create the GitHub repo and push (5 min)

Create a **public**, empty repo: `ArtKeyAi/bhived-python`. Don't add a README, license or .gitignore on GitHub, since the repo already has them. Then:

```bash
cd C:\Users\Yossuf\Desktop\bhived\bhived-python
git remote add origin https://github.com/ArtKeyAi/bhived-python.git
git push -u origin main
```

Or do both at once with the GitHub CLI:

```bash
gh repo create ArtKeyAi/bhived-python --public --source . --remote origin --push
```

On the repo page, set:

- Website: `https://bhived.ai/docs/integrations/langchain`
- Description: `Python client and LangChain middleware for bhived shared lessons`
- Topics: `langchain`, `langchain-middleware`, `ai-agents`, `agent-memory`, `python`

Check that the **CI** workflow goes green on the first push (Actions tab).

## 3. Set up PyPI trusted publishing (15 min)

This lets GitHub Actions publish without storing a PyPI token.

1. On GitHub: repo **Settings → Environments → New environment**, name it `pypi`. Optional but recommended: add yourself under "Required reviewers", so every release waits for your click.
2. On [pypi.org](https://pypi.org) (logged in, with 2FA on): **Your account → Publishing → Add a new pending publisher**. Add it twice, once per package:

| Field | First entry | Second entry |
|---|---|---|
| PyPI Project Name | `bhived` | `langchain-bhived` |
| Owner | `ArtKeyAi` | `ArtKeyAi` |
| Repository name | `bhived-python` | `bhived-python` |
| Workflow name | `publish.yml` | `publish.yml` |
| Environment name | `pypi` | `pypi` |

A pending publisher turns into the real project the first time the workflow publishes.

## 4. Publish both packages (10 min)

`langchain-bhived` depends on `bhived`, so `bhived` goes first.

```bash
git tag bhived-v0.1.0
git push origin bhived-v0.1.0
```

Wait until the **Publish** workflow finishes (approve it under the `pypi` environment if you added yourself as a reviewer). Check that https://pypi.org/project/bhived/ shows 0.1.0. Then:

```bash
git tag langchain-bhived-v0.1.0
git push origin langchain-bhived-v0.1.0
```

Check https://pypi.org/project/langchain-bhived/. Then test the published package in a clean folder:

```bash
python -m venv C:\temp\lcb-check
C:\temp\lcb-check\Scripts\pip install langchain-bhived
C:\temp\lcb-check\Scripts\python -c "import langchain_bhived; print(langchain_bhived.__version__)"
```

If a workflow fails at "Check the tag matches the package version", the tag and `_version.py` don't agree. Delete the tag (`git push origin :refs/tags/<tag>`), fix it, and tag again. PyPI never lets you reuse a version number, so if something wrong got published, bump to 0.1.1 instead.

## 5. Put the docs page on bhived.ai (30 to 60 min, in the `bhived-website` repo)

The draft is `docs/langchain.md` in this repo. It has the same frontmatter as the existing pages in `bhived-website/docs-drafts/`.

The website needs three code changes before `/docs/integrations/langchain` works. The current docs route, `src/app/(marketing)/docs/[slug]/page.tsx`, only serves one path segment, so a nested URL returns 404 today.

1. Copy `docs/langchain.md` to `bhived-website/docs-drafts/integrations/langchain.md`. `getDocBySlug` reads `docs-drafts/<slug>.md`, so a slug of `integrations/langchain` finds that file.
2. In `src/lib/docs.ts`:
   - add an `"integrations"` id to `DocCategoryId` and a matching entry to `docCategories` (title "Integrations", description "Use bhived from agent frameworks.").
   - add a `DocConfig` entry: slug `integrations/langchain`, path `/docs/integrations/langchain`, title "bhived for LangChain", navTitle "LangChain", category `integrations`, and seoTitle, description, primaryQuery, secondaryQueries, lastUpdated and schemas copied from the draft's frontmatter. For howToSteps use: "Install langchain-bhived with pip.", "Run npx bhived setup or set BHIVED_API_KEY.", "Add BhivedMiddleware() to create_agent.", "Optionally add BhivedToolkit().get_tools() for write-back."
3. Add a route for the nested URL. Either create `src/app/(marketing)/docs/integrations/[slug]/page.tsx` that renders the doc for `integrations/${slug}` (copy the existing `[slug]` page and change the lookup and `generateStaticParams`), or turn the existing route into a catch-all `[...slug]`. Make sure the sitemap and `llms.txt` pick up the new page.

The decision doc also suggests a small hub page at `/docs/integrations` that lists this page (and the Strands and Microsoft pages later). That's useful but not needed for the LangChain listing.

Deploy, then check that:

- https://bhived.ai/docs/integrations/langchain returns 200 and renders the code blocks and tables
- the page links to PyPI and to GitHub, and both links work
- the page shows up in https://bhived.ai/sitemap.xml

Do this **before** step 6. The listing links to this URL, and the people reviewing it may click it.

## 6. File the LangChain integration issue (10 min)

Open https://github.com/langchain-ai/docs/issues/new?template=06-integration-submission.yml and fill in:

| Field | Value |
|---|---|
| Display or class name | `BhivedMiddleware` |
| Language | `Python` |
| Component type | `middleware` |
| PyPI package name | `langchain-bhived` |
| npm package name | leave empty |
| Docs URL | `https://bhived.ai/docs/integrations/langchain` |
| Source repository | `ArtKeyAi/bhived-python` |
| Short provider description | `Recalls shared lessons from the bhived network before model calls and adds tools to write verified lessons back.` |
| Capability flags | leave empty |
| Confirmations | tick "The package is already published on PyPI and/or npm." |

Don't open a docs PR yourself. LangChain's automation closes manual PRs. A maintainer adds a label, and a bot opens the PR.

## 7. After it's merged (5 min)

The bot PR usually merges within about a day. Then check the raw HTML of https://docs.langchain.com/oss/python/integrations/middleware and confirm the bhived row links to `https://bhived.ai/docs/integrations/langchain` without `nofollow`. Log the result in the marketing `tracking.md`.

## Things to know

- **The REST API is now a public contract.** These packages call `POST /v2/query` and `POST /v1/memories` with the `X-API-Key` header. A breaking change to either endpoint breaks every installed copy. Version the API before changing it.
- **Writes only happen when the model calls a write tool.** Nothing is captured automatically. With a personal key a write is a public lesson. With a team key it stays private to the team, and the server enforces that. The tool descriptions spell out what must never be written.
- **Tested versions:** the full suite passes on LangChain 1.4.7 and 1.4.8 (langchain-core 1.7.3 and 1.7.4), with httpx 0.27 and 0.28, on Python 3.13, both from the source tree and from the built wheels. The package allows `langchain>=1.1` because the middleware API it uses (`ModelRequest.system_message`) first shipped in 1.1.0. A fresh install pinned to LangChain 1.1 or 1.2 currently breaks inside LangGraph itself (its newer helper packages don't match the old pins), so those versions couldn't be tested.
- **What wasn't tested:** nothing ran against a real LLM, and nothing ever wrote to the live API. The end-to-end tests run LangChain's real `create_agent` with a scripted model and a mocked bhived API. One read-only query against the live API passed.
