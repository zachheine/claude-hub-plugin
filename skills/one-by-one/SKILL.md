---
name: one-by-one
description: Ask the user questions ONE AT A TIME instead of as a list — hold a numbered backlog, ask the next question only after the previous answer lands, accept skip / later / you-decide, and close with a decisions summary. Use when the user says "one at a time", "one by one", "ask me one question at a time", "too many questions", "walk me through these", or when you are about to ask more than two questions in a single message.
---

# One at a time

A list of seven questions gets zero answers. One question gets one answer, and then the next. From the moment this skill is invoked until the backlog is empty, every question you have for the user goes through this procedure.

## Procedure

1. **Build the backlog.** Write every open question as one line each, numbered, most consequential first. Fold duplicates. Drop any you can answer yourself from the code, the repo, or a sensible default; say which you dropped and what you assumed. Show the backlog once: "N questions. Starting with the one that unblocks the most."
2. **Ask exactly one.** One question per message, with the context needed to answer it in two or three sentences, and your recommendation when you have one. If the question-asking tool is available, use it with two to four options plus the recommended one first; otherwise ask in prose. Nothing else goes in that message: no status, no second question, no "also".
3. **Wait.** Do not proceed, do not pre-empt, do not answer it yourself.
4. **Record and move on.** Restate the answer in one line, mark it on the backlog ("3 of 7 done"), and ask the next. Three words the user can always say: **skip** (ask again at the end), **later** (drop it from this pass; note it as open), **you decide** (take your recommendation and say so).
5. **Close.** When the backlog is empty, post one summary: every question with its answer or its disposition, in the original numbering. Then act on them.

## Rules

- A question that arrives mid-pass (new discovery, a spoke's report) joins the backlog; it does not jump the queue unless it blocks the current one.
- Never batch "while I have you" extras onto a question. The whole point is one thing on screen.
- If the user answers several at once anyway, record them all, confirm in one line, and continue from the first unanswered.
- In a hub session, "waiting on you" lists are asked this way whenever the user has invoked this skill in that session; the hub board can keep the list, the conversation does not.
