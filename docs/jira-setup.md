# Jira setup

The Jira connector is off until you set it. Nothing in the demo calls Jira. Use a site you control, and do not point it at a project that holds export-controlled requirements unless that site is allowed to store them.

Jira, and the Atlassian account pages named below, are Atlassian products. VeriReq is not affiliated with or endorsed by Atlassian.

## Cloud

1. Create a free Jira Cloud site from Atlassian's Jira signup page. The site looks like `https://your-site.atlassian.net`.
2. Create a project and note its key, such as `DEMO`. The key is letters and digits only.
3. In the Atlassian account security settings, create an API token. Copy it once. Do not commit it and do not paste it into the web page.
4. Export the variables and start the app:

```bash
export JIRA_BASE_URL=https://your-site.atlassian.net
export JIRA_EMAIL=you@example.com
export JIRA_API_TOKEN='paste-token-here'
export JIRA_PROJECT=DEMO
export JIRA_DEPLOYMENT=cloud
python -m verireq
```

`JIRA_PROJECT_KEY` is accepted as another name for `JIRA_PROJECT`. Leave `JIRA_EMAIL` unset only for Server or Data Center.

Open Verify and click **Test Jira connection**. A 401 means the email or token was rejected. A 403 means the account is signed in but not allowed to see the project. A 404 means the project key or the site URL is wrong.

## Server or Data Center

Set `JIRA_DEPLOYMENT=server`. Use a personal access token as `JIRA_API_TOKEN`. The connector sends it as a bearer token and calls REST API v2. The description is plain text, not Atlassian document format. The base URL must be `https`. A context path such as `https://jira.example.com/jira` is kept.

## What a push does

The preferred issue type is `Requirement` unless `JIRA_ISSUE_TYPE` names another type. If the project has no Requirement type, or Jira rejects it, the connector tries Story and then Task. A second push for the same requirement updates the existing issue. The match is the stored issue key, or a Jira label `verireq-` plus the requirement id. Parent links use the Relates link type. Depends-on links use Blocks. Override either with `JIRA_PARENT_LINK` or `JIRA_DEPENDS_LINK`.

Status pull reads issues in batches. Cloud uses `/rest/api/3/search/jql` and `nextPageToken`. Server and Data Center use `/rest/api/2/search` and `startAt`. Map extra status names with `JIRA_STATUS_MAP`, a JSON object whose values are `Not started`, `Planned`, `In progress`, `Passed`, `Failed`, or `Waived`.

## Live test

The live test is skipped in CI. On a machine where the variables above are set, including `JIRA_EMAIL` for Cloud:

```bash
python -m pytest -q -m jira_live
```

The test creates one issue, reads it back, and deletes it. If delete fails, remove that issue from the project by hand.
