# Publish checklist: tokens to fill in

The README and docs carry a few links that don't exist yet: the public repository, the release downloads and the
demo video. Each one is marked with a single token, `PUBLISH-TODO:NAME`, inside an HTML comment. The page reads
cleanly ("coming with the first release"), and the token shows exactly where the link goes.

Before you publish, fill in every token below. Then run the check:

```bash
python scripts/check_publish_tokens.py --strict   # exit 0 = no token left
```

| Token | Where | What to put there | Ready when |
|---|---|---|---|
| `PUBLISH-TODO:REPO_URL` | README.md, "Setup and run" | The public repository URL (`git clone <URL> opensoul`). Put the clone command back into both code blocks. | The anonymous GitHub account and the public repository exist. |
| `PUBLISH-TODO:RELEASES_URL` | README.md, "Download" | The release page URL. Link each package name in the table to its file. | The first release with the five packages is published. |
| `PUBLISH-TODO:DEMO_VIDEO_URL` | README.md, top | The demo video URL (2 minutes or less). | The demo video is uploaded. |
| `PUBLISH-TODO:DEMO_LOOP_IMAGE` | README.md, top | A 6–8 s loop image (Describe → Master → Sheet → Shot → Share), made only from logged open-model assets. Optional. | The loop is made and passes the prepublish gate. |

Rules:

- Never invent a URL. Leave the token until the real link exists.
- When you fill in a token, delete its comment and its "coming with the first release" text.
- Remove a row from this table only when its token is gone. `tests/test_publish_tokens.py` checks that this table
  and the tokens in the repository agree.
