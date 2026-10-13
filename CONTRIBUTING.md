# Contributing

Thanks for helping developers build with Chariot. A few rules keep this repo useful and safe.

## What an example looks like

Each example is one self-contained folder. Quickstarts (under `quickstarts/`) teach one API surface; integrations (under `integrations/`) ship a drop-in service class for one framework plus a runnable demo. Customer diagnostics live under `tools/` with documented measurement boundaries and the same self-contained setup.

```
quickstarts/<api-surface>/     or     integrations/<framework>/     or     tools/<tool>/
  README.md          what it does, how to run it, what to try
  .env.sample        every variable the example reads, with placeholder values
  requirements.txt   its own dependencies (Python) or package.json (JS)
  *.py / *.ts        a small number of flat, readable files
```

- It must run after `pip install -r requirements.txt` plus copying `.env.sample` to `.env`. No hidden setup.
- Keep it small. An example teaches one thing; a second idea is a second example.
- Point only at public endpoints (`api.chariot.in`) and the public console ([platform.chariot.in](https://platform.chariot.in)).

## Ground rules

- **Never commit a credential.** Placeholders like `your-api-key` only, and every variable an example reads belongs in its `.env.sample`.
- **Public surfaces only.** If an endpoint is not in the public docs, it does not belong in an example.
- **Show, do not compare.** Examples demonstrate what Chariot does; leave other products out of it.

## Style

- Plain, direct README prose. Show the command before explaining it.
- Code comments explain decisions, not syntax.
- No em dashes in any text in this repo.
