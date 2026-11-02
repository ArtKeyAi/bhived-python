# Founder steps: from this folder to three framework listings

Everything here is built and tested locally. Nothing has been pushed, published, deployed or filed. These are the steps only you can do, in order. Each one depends on the one before it.

The three listings are LangChain, Strands and Microsoft Agent Framework. Space them out: LangChain first, then Strands about a week later, then Microsoft about a week after that.

Checked on 2026-11-03: the PyPI names `bhived`, `langchain-bhived`, `strands-bhived` and `agent-framework-bhived` are free, and `ArtKeyAi/bhived-python` doesn't exist on GitHub yet.

## 1. Look it over (5 min, optional)

```bash
cd C:\Users\Yossuf\Desktop\bhived\bhived-python
.venv\Scripts\python -m pytest
.venv\Scripts\python examples\offline_demo.py
```

Expect `123 passed, 1 skipped` (the skipped one is the optional live test). The demo prints the prompt block the model sees.

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

- Website: `https://bhived.ai/docs/integrations`
- Description: `Python client and framework adapters (LangChain, Strands, Microsoft Agent Framework) for bhived shared lessons`
- Topics: `langchain`, `langchain-middleware`, `strands-agents`, `agent-framework`, `ai-agents`, `agent-memory`, `python`

Check that the **CI** workflow goes green on the first push (Actions tab).

## 3. Set up PyPI trusted publishing (15 min)

This lets GitHub Actions publish without storing a PyPI token.

1. On GitHub: repo **Settings → Environments → New environment**, name it `pypi`. Optional but recommended: add yourself under "Required reviewers", so every release waits for your click.
2. On [pypi.org](https://pypi.org) (logged in, with 2FA on): **Your account → Publishing → Add a new pending publisher**. Add one per package, four in total. Every field is the same except the project name:

| Field | Value |
|---|---|
| PyPI Project Name | `bhived`, then `langchain-bhived`, then `strands-bhived`, then `agent-framework-bhived` |
| Owner | `ArtKeyAi` |
| Repository name | `bhived-python` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

A pending publisher turns into the real project the first time the workflow publishes.

## 4. Publish the packages (15 min)

All three adapters depend on `bhived`, so `bhived` goes first.

```bash
git tag bhived-v0.1.0
git push origin bhived-v0.1.0
```

Wait until the **Publish** workflow finishes (approve it under the `pypi` environment if you added yourself as a reviewer). Check that https://pypi.org/project/bhived/ shows 0.1.0. Then push the adapter tags, one at a time, waiting for each run:

```bash
git tag langchain-bhived-v0.1.0
git push origin langchain-bhived-v0.1.0
```

```bash
git tag strands-bhived-v0.1.0
git push origin strands-bhived-v0.1.0
```

```bash
git tag agent-framework-bhived-v0.1.0
git push origin agent-framework-bhived-v0.1.0
```

You can hold back the Strands and Microsoft tags until the week you file those listings. The listings need the package on PyPI, nothing more.

Test each published package in a clean folder, for example:

```bash
python -m venv C:\temp\lcb-check
C:\temp\lcb-check\Scripts\pip install langchain-bhived
C:\temp\lcb-check\Scripts\python -c "import langchain_bhived; print(langchain_bhived.__version__)"
```

If a workflow fails at "Check the tag matches the package version", the tag and `_version.py` don't agree. Delete the tag (`git push origin :refs/tags/<tag>`), fix it, and tag again. PyPI never lets you reuse a version number, so if something wrong got published, bump to 0.1.1 instead.

## 5. Review, merge and deploy the website branch (20 min)

The website change already exists as a local branch, **`docs-integrations`**, in `C:\Users\Yossuf\Desktop\bhived\bhived-website`. It starts from `gemini` (your live branch), and your checkout wasn't touched: you're still on `gemini`, and the untracked `public/brand/icon-512-black.png` is still there. The branch has two commits by `Yossuf Yahia <yossufyahya2000@users.noreply.github.com>`. It adds:

- `docs-drafts/integrations/langchain.md`, `strands.md` and `microsoft-agent-framework.md`
- an "Integrations" category and three entries in `src/lib/docs.ts`
- the route `src/app/(marketing)/docs/integrations/[slug]/page.tsx` for the nested URLs
- a hub page at `/docs/integrations`
- `src/components/docs/DocArticlePage.tsx`, the old `[slug]` page body moved into a shared component so both routes render the same way (the top-level docs pages look the same as before)
- a `publicRoutes` entry for the hub in `src/lib/seo.ts`. The sitemap and `llms.txt` read `publicRoutes`, so all four new URLs appear in both

It passed `tsc --noEmit`, `eslint` on the changed files, and `npm run build`. The build lists the hub and all three integration pages, and the 7 existing docs pages still build.

To review and ship it:

```bash
cd C:\Users\Yossuf\Desktop\bhived\bhived-website
git log --oneline gemini..docs-integrations
git diff gemini...docs-integrations --stat
```

If it looks right, merge it into `gemini` and deploy the way you normally do. Then check:

- https://bhived.ai/docs/integrations and https://bhived.ai/docs/integrations/langchain return 200 and render the code blocks and tables
- https://bhived.ai/docs/integrations/strands and https://bhived.ai/docs/integrations/microsoft-agent-framework return 200 too
- each page links to its PyPI package and to GitHub. The PyPI links only work once step 4 is done for that package.
- the pages show up in https://bhived.ai/sitemap.xml and https://bhived.ai/llms.txt

Do this **before** step 6. The listings link to these URLs, and the people reviewing them may click through.

## 6. File the LangChain integration issue (10 min, week of Nov 10)

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

Don't open a docs PR yourself. LangChain's automation closes manual PRs. A maintainer adds a label, and a bot opens the PR. It usually merges within about a day.

Afterwards, check the raw HTML of https://docs.langchain.com/oss/python/integrations/middleware and confirm the bhived row links to `https://bhived.ai/docs/integrations/langchain` without `nofollow`. Log the result in the marketing `tracking.md`.

## 7. Open the Strands catalog PR (15 min, about a week later)

`strands-bhived` must be on PyPI first (step 4).

1. Fork `strands-agents/harness-sdk` on GitHub.
2. Add one file, `site/src/content/catalog/strands-bhived.yaml`, with exactly this content (put the day you open the PR in `addedDate`):

```yaml
name: strands-bhived
description: Recalls shared lessons (verified fixes and known mistakes) from the bhived network before each run and adds tools to write lessons back.
integrationType: plugin
languages:
  python:
    package: strands-bhived
github: https://github.com/ArtKeyAi/bhived-python
docsUrl: https://bhived.ai/docs/integrations/strands
maintainedBy: partner
addedDate: <the day you open the PR>
```

3. Open the PR with the catalog template by adding `?template=catalog-submission.md` to the compare URL.

Leave `featured` and `badges` unset, and don't add docs pages under `site/`. If the bot asks for a CLA or DCO sign-off, sign it.

## 8. Open the Microsoft Agent Framework PR (20 min, about a week after Strands)

`agent-framework-bhived` must be on PyPI first (step 4).

1. Fork `microsoft/agent-framework`.
2. Edit only `python/samples/community-projects.md`. In the **Context providers** table, add this row, keeping the table sorted alphabetically (Bhived goes first):

```
| Bhived | A context provider that recalls shared lessons from the bhived network before agent runs, with function tools to write verified lessons back. | Shared cross-agent lesson recall before runs; explicit lesson write-back tools; team-private lessons with a team key | [agent-framework-bhived](https://bhived.ai/docs/integrations/microsoft-agent-framework) | [Open an issue](https://github.com/ArtKeyAi/bhived-python/issues/new/choose) |
```

3. Title the PR `Python: Add Bhived to the Python community projects`. In the body:
   - say the package is published, and link https://pypi.org/project/agent-framework-bhived/
   - link the tests: https://github.com/ArtKeyAi/bhived-python/tree/main/packages/agent-framework-bhived/tests
   - say it implements a `ContextProvider` (`before_run` only, nothing captured after a run) plus function tools
   - say there is no Microsoft endorsement or compatibility claim
4. Sign the Microsoft CLA when the bot asks.

If a reviewer asks for a repo link instead of the docs URL, accept it. The listing still helps the brand and AI answers; only the link equity goes to GitHub instead of bhived.ai.

## Things to know

- **The REST API is now a public contract.** These packages call `POST /v2/query` and `POST /v1/memories` with the `X-API-Key` header. A breaking change to either endpoint breaks every installed copy. Version the API before changing it.
- **Writes only happen when the model calls a write tool.** No adapter captures anything automatically: the LangChain middleware, the Strands plugin and the Agent Framework provider only read. With a personal key a write is a public lesson. With a team key it stays private to the team, and the server enforces that. The tool descriptions spell out what must never be written. The Agent Framework tools can also require approval for every write (`write_approval_mode="always_require"`).
- **Shared code:** the tool descriptions, error messages, recall cache and the "Shared lessons" block live once in the core package (`bhived.adapter`, `QueryResult.as_context`), so all three adapters give the model the same guidance.
- **Tested versions:** everything ran on Python 3.13, both from the source tree and from the four built wheels installed in a fresh environment.
  - LangChain: the suite passes on 1.4.7 and 1.4.8 (langchain-core 1.7.3 and 1.7.4) with httpx 0.27 and 0.28. The package allows `langchain>=1.1` because the middleware API it uses first shipped in 1.1.0. Fresh installs pinned to LangChain 1.1 or 1.2 currently break inside LangGraph itself, so those versions couldn't be tested.
  - Strands: the suite passes on strands-agents 1.63.0. The package allows `>=1.45` because the `ContextInjector` plugin it builds on exists, with the same signature, from 1.45.0 (checked in the published wheels); only 1.63.0 was run.
  - Agent Framework: the suite passes on agent-framework-core 1.24.0. The package allows `>=1.0` because `ContextProvider.before_run`, `SessionContext.extend_instructions` and `@tool` have the same shape in 1.0.0 (checked in the published wheel); only 1.24.0 was run.
- **What wasn't tested:** nothing ran against a real LLM, and nothing ever wrote to the live API. The end-to-end tests run each framework's real agent (`create_agent`, Strands `Agent`, Agent Framework `Agent`) with a scripted model and a mocked bhived API. One read-only query against the live API passed.
