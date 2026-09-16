# YouTube monetization policy — research

Last updated: 2026-09-15

This is primary-source research, not analysis or a decision — see [decisions/](../decisions) for how the pipeline responds to what's documented here.

## Inauthentic content policy

Source: YouTube's official "YouTube channel monetization policies" page (support.google.com/youtube/answer/1311392), fetched 2026-08-12.

There is no way to guarantee with certainty that a given video won't be flagged. The policy is enforced by human reviewer judgment against qualitative language, not an automated check against a fixed threshold, so "100% certain" isn't an achievable target — the honest goal is minimizing risk by deliberately building toward the stated criteria, not eliminating it.

Not allowed to monetize: "AI-generated content made with generic or unoriginal templates giving the impression of mass production without adding the creator's original, authentic insights or perspective," "image slideshows, templated storylines, or scrolling text with minimal or no narrative, commentary, or educational value," and content that "stitches together unrelated or inconsistent AI clips" without a cohesive narrative arc.

Allowed to monetize: content with "a cohesive storyline that doesn't rely solely on shock value," content that "expresses your unique creative voice, like using AI to visualize a unique character and narrative you invented," and content that "utilizes creative tools to assist in delivering a unique, well-researched, or creative narrative" as long as "the final product still demonstrates your creative vision." A consistent intro/outro across videos is explicitly fine — what has to vary is the substance.

Reviewers also assess a channel as a whole (its main theme, most-viewed and newest videos, metadata, About section), not just one video in isolation, so consistency of quality and premise across the channel matters, not only individual-video polish.

**Correction:** an earlier version of this project's docs cited a "three-strike" enforcement mechanism specific to this policy, sourced from a secondary summary. That does not appear on YouTube's own monetization policy page and has been removed pending further verification. YouTube does have a well-documented three-strikes system, but it's for Community Guidelines violations generally — it is not confirmed as the mechanism for inauthentic-content monetization decisions specifically.

### Mapped to the pipeline

The research and fact-check stages should aim for genuine, specific findings rather than a generic summary, since "original, authentic insights" is explicit policy language. The narrative and narrative-quality-review stages should be scored directly against "cohesive narrative arc" and "materially varied" substance, not just a general "is this good" rubric. The shot list and previz stages should be checked for visual coherence across the sequence, specifically to avoid the "stitched together unrelated or inconsistent AI clips" failure mode called out by name in the policy.

## What actually happens if a video gets flagged

Source: YouTube's "Monetization is disabled for my channel" page (support.google.com/youtube/answer/1727191), fetched 2026-08-12.

There's a warning stage before any channel-level penalty: if a portion of a channel is found out of line with monetization policy, YouTube sends a "scheduled for suspension" notice with a 7-day window to appeal before the suspension takes effect. Appealing in time pauses the scheduled suspension while it's reviewed (response within 14 days). If the window is missed or the appeal is rejected, the channel is suspended from the Partner Program — at which point you can appeal within 21 days, or simply re-apply after 90 days.

For monetization-policy violations specifically (the category inauthentic content falls under), the documented recovery path is "fix it and try again": review the flagged videos against policy, edit or delete the ones that violate it, then re-apply. YouTube's review team re-examines the channel; the decision takes about a month.

Important distinction: this "edit or delete to fix it" path applies to monetization-policy issues, not to Community Guidelines strikes or copyright strikes — for those, deleting the video explicitly does not resolve the strike, a formal appeal of the strike itself is required instead. That's a separate, harsher system.

Net effect: a channel finding its footing can expect a working correction loop (warning → fix → resume, or suspend → correct → re-apply) rather than a single irreversible failure condition.

## Monetization thresholds

Full ad monetization requires 1,000 subscribers and either 4,000 watch hours in 12 months or 10 million Shorts views in 90 days, plus a linked AdSense account. These are audience thresholds independent of content quality — no amount of pipeline quality shortcuts them.

## Video length rules

YouTube's Shorts max length is 3 minutes (raised from 60 seconds in October 2024), but the best-performing range is roughly 30–60 seconds, with 50–60 second Shorts substantially outperforming anything under 10 seconds. Mid-roll ad eligibility for long-form video requires a minimum of 8 minutes.

## Violence, horror, and visual realism

Sources: YouTube's "Advertiser-friendly content guidelines" (support.google.com/youtube/answer/6162278) and "Disclosing use of altered or synthetic content" (support.google.com/youtube/answer/14328491), both fetched 2026-09-15.

Researched after this project committed to horror ([decisions/0037](../decisions/0037-horror-motion-comic-shorts-wan-via-replicate.md)), to check a specific worry: that photorealistic horror might be flagged more harshly than stylized horror. The answer splits across two different policies that pull in different directions.

### The violence policy does not care about visual style

The advertiser-friendly guidelines distinguish **real-world** violence from **dramatized** violence, not photorealistic from stylized. "Dramatized content depicting non-graphic violence or graphic violence" is monetizable, explicitly including "fighting violence excerpts from an action movie (such as scripted content) where injuries are mostly indiscernible." Real graphic imagery — actual dead bodies outside an educational context — gets no ads. Context (news, educational, artistic, documentary) is stated as materially important.

An AI-generated horror short is dramatized fiction whether it is rendered photorealistically or as a cartoon, so on this axis the choice of visual style is not the thing being judged. One caveat worth stating as unverified: the policy language assumes a reviewer can tell fiction from real footage. Whether an *automated* first-pass classifier reliably makes that distinction on photorealistic AI video is not addressed by any source found, and should be treated as an open risk rather than a documented one.

### The synthetic-content disclosure policy cares a great deal about visual style

This is where realism has a real, documented cost. Creators must disclose content that is "realistic" — meaning "content a viewer could easily mistake for a real person, place, scene, or event" — when it is generated or meaningfully altered with AI. Disclosed realistic content carries a label, and "for photorealistic AI content, a label in the video player may also appear."

Content that is "clearly unrealistic, animated, includes special effects, or has used generative AI for production assistance" is explicitly **exempt** from the disclosure requirement.

YouTube states that disclosure itself "won't limit a video's audience or impact its eligibility to earn money," so this is not a monetization penalty. But it is a real operational difference: photorealistic output creates a per-upload disclosure obligation and a viewer-facing label, and YouTube "may add a label even when a creator hasn't disclosed it." Stylized output avoids that category entirely.

### Mapped to the pipeline

Neither policy forbids photorealistic horror. The practical asymmetry is that stylized output sits outside the synthetic-content disclosure regime, while photorealistic output sits inside it. That is a point in favour of stylized as a *default*, not an argument against ever choosing realism — which is consistent with treating style as a per-video decision rather than a global one.
