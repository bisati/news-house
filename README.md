# News House

A newspaper with one reader. Every morning it reads 244 sources, decides what matters to me, and writes a paper I can finish in fifteen minutes. Then it stops.

**Live at:** [news-house.vercel.app](https://news-house.vercel.app) · [a good day](https://news-house.vercel.app/2026-11-07.html)

I was spending about two hours a day on Instagram for ten minutes of value. The feed ranks for eyeballs, so the things that matter to me arrived late, buried, or not at all, and always in the same flat template. News House ranks for one question instead: *how much would I regret not knowing this today?* It writes every post against a profile of who I am and what I work on, and it ends with "you're caught up". Nothing loads past that.

## How it works

Every two hours my Mac pulls the sources, groups stories that are about the same event, and asks a small model to score each one for me. The first run after 6 am builds the day's paper: the top stories go to a larger model, which writes each post and picks how to show it.

That is the easy half. The hard half is believing what comes back.

**The writer chooses; code checks.** The model decides what kind of story it is looking at and picks one of thirteen visual formats for it: a fact sheet for a launch, *what changes for you* for a new rule, a number in context, a court case as its steps, a transfer as a deal, a rumour checked against who is actually saying it. Each format has a strict shape, and code checks every one before it reaches the page:

- every number in a visual must appear in a source the post cites, by value, not by string;
- every name must appear in those sources, spelled the way they spell it;
- dates must be written in a source, a scoreline must sit next to the teams it belongs to, and a countdown must count to a day that is actually coming.

A visual that fails gets one retry with the problems listed. If it fails again, the post loses its visual, never its text, and falls back to the source's own photo. A wrong number costs a picture, not a story.

## Product decisions

- **A visual has to say something.** The first version put the biggest number in giant type on half the posts. It looked designed and said nothing. Each format now answers the question a reader of that kind of story actually has: *what changes for me, and from when?* for a rule; *who is out, and for which games?* for an injury. If the sources cannot fill the format, the post gets a simpler one, or none.
- **The story picks the format, not the template.** People, deaths, disasters and events get a photo. Launches, rules and numbers keep their fact format, because a press photo of a product tells you less than its price and its date. The paper warns itself when fewer than four in five posts carry a visual, or when one format takes more than a third of the paper.
- **Taste in the model, rules in the code.** The model picks the format and which slide of a carousel deserves the highlight colour. Code decides whether its facts hold up. Neither is asked to do the other's job.
- **Colour is a ladder, not a palette.** The lead story gets the deep colour, good news gets mint, breaking news gets a red bar (at most two a day), and everything else is white. No two coloured posts sit next to each other, so colour keeps meaning something.
- **The feed ends.** A finite paper is the whole point, and it is a decision no product paid for by attention can make. No streaks, no "more like this", no infinite scroll.

## What I'd point at

- [`newshouse/catalogue.py`](newshouse/catalogue.py): the thirteen formats and the checks that decide whether a visual is true.
- [`newshouse/llm/prompts/write.system.md`](newshouse/llm/prompts/write.system.md): the writer's brief, including the table that maps a kind of story to its format.
- [`docs/design-visuals.md`](docs/design-visuals.md): the spec for the formats, written before any of them were built.
- [Running it yourself](docs/running.md): setup, the schedule on a Mac, and how the page reaches a phone.
- [How this was built](docs/how-this-was-built.md): spec, then a cold read by a fresh agent, then a plan, then each task built and reviewed by separate agents.

## Stack

Python · SQLAlchemy · Jinja · plain CSS and JS, no framework · Claude (Haiku to score, Opus to write) · Vercel for the page · one Neon table so taps on my phone reach the Mac · 600+ tests.

The repo ships with a fictional reader profile and sample sources. Your own profile stays on your machine.
