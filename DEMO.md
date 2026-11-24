# DemoSat walkthrough

About ten minutes. Start with `python -m verireq` or `docker run --rm -p 127.0.0.1:8000:8000 verireq`. Do not set `LLM_*` or `JIRA_*`. Say that the checker is local: requirement text stays in this process.

DemoSat is a fictional small satellite. The set is about fifty requirements, with parents, dependencies, a duplicate, a mass contradiction, draft verification methods, some evidence, and two reviewers.

## 0:00 Open

Show the wordmark, Engineering Intelligence, and the banner that the model pass and the Jira connector are off. Point at the NASA profile, marked default, and the method chips: Test, Analysis, Inspection, Demonstration.

Say: "We start from a NASA systems-engineering profile. The other profiles are data files. ECSS is still one of them, with Review of design instead of Demonstration."

## 1:00 Load the project

Click **Load demo project**. The app opens Verify.

Say: "This did not upload a file and it did not call a service. DemoSat ships inside the app."

## 2:00 Verify

Stay on VeriReq Verify. Show the closure ring, then the four method counts.

Say: "A requirement is closed only when the status is Passed or Waived and an evidence reference is filled in. Passed with an empty evidence cell stays open, labelled Evidence missing."

Scroll to a Passed row with an evidence id, then to the payload cover marked Failed. Change one evidence field and point at the ring if it moves.

Say: "The method is a draft from the wording. The engineer confirms it."

## 4:00 Spec

Open VeriReq Spec. Show parent and depends-on columns.

Say: "Spec is where the set is authored or imported. CSV, Excel, DOCX, PDF text, and ReqIF all land in this table. Reuse suggestions come from a local library, not from a search service."

## 5:30 Analyze

Open VeriReq Analyze. Filter the story with three rows:

- the duplicate launch-mass statement
- "should be easy" and "will carry a camera", which this profile does not treat as binding
- the two structure statements, one not exceeding 4 kg and one at least 6 kg

Say: "The profile decides what shall, should, and will mean. The contradiction check is lexical. It is a prompt for a reviewer, not a ruling."

## 7:00 Trace

Open VeriReq Trace. Show the tree: mission at the left, subsystems to the right. Point at the broken dependency and the note that has no parent.

Say: "Parent links and dependencies are data on the requirement. The graph and the findings are the same links."

## 8:00 Insight

Open VeriReq Insight. Show the closed count, the disagreement count, and the two reviewer fields on the flight-software row where the priorities differ.

Say: "Two reviewers on the same milestone. If priority or disposition differs, the row is flagged. The names here are Reviewer 1 and Reviewer 2."

## 9:00 Take the files with you

Back on Verify. Click **Export workbook**, then **Export ReqIF**, then **Export Xray JSON**. Leave **Push to Jira** disabled.

Say: "The workbook, the ReqIF file, and the Xray JSON are downloads. ReqIF is the interchange format tools such as DOORS, DOORS Next, and Polarion can read. Those names belong to their owners. This tool is not affiliated with them, and it does not claim a certified connection. Jira stays off until someone sets a base URL and a token, and that token is never written into the page."

Close on the banner: export-controlled text stays here only while the model pass and the Jira connector remain off.
