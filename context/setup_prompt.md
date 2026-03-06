# JeZR Athlete Profile Generation Prompt

Copy everything below this line and paste it into your AI of choice (Claude, ChatGPT, etc.).
Answer the questions conversationally — the more detail you provide, the better your coaching context will be.
When finished, save the two output files to your JeZR `context/` directory.

---

## THE PROMPT

You are helping me set up JeZR, an AI training coach system. I need you to generate two files that form my athlete profile — a structured JSON file and a narrative coaching context document.

Ask me questions one at a time to gather everything you need. Don't rush through them — follow up if an answer is vague or if something I say raises an obvious follow-up question. Think of this as the conversation I'd have with a new coach on day one: everything they'd need to know about me as an athlete to work with me effectively.

Work through these areas in order, but follow the conversation naturally:

**1. Basic details**
Name, age, what sports I train for (running, cycling, triathlon, etc.)

**2. Goals**
What am I training for right now — race, distance, target time, date? What's the bigger long-term ambition beyond that?

**3. Current training**
What does a typical week look like? How many km running, hours riding? What's my longest run and ride right now? What phase am I in — base building, build, peak, taper?

**4. Performance benchmarks**
What is my current threshold pace per km (from Intervals.icu settings)? If I ride with a power meter, what is my FTP? What are my recent race times or key session benchmarks?

**5. Injury history**
What injuries have I had? Be specific — which body part, when, how bad, how long to recover, what the warning signs were, and what conditions seem to bring it back. This is one of the most important sections.

**6. Risk flags and constraints**
What should my coach actively avoid in my training plan? What scheduling constraints do I have — travel, work, family? What days can I train and what fits on each day?

**7. How I respond to training load**
Do I absorb volume well or does intensity hit me harder? How do I know when I'm carrying too much fatigue — heavy legs, elevated HR, poor sleep, mood? Do I tend to push through when I should back off?

**8. Riding and cross-training**
If I ride — Zwift, outdoor, or both? Do I treat rides as recovery or training? Are there specific ride formats that leave me cooked for days (long climbs, Zwift races, hard intervals)? How do I balance riding and running in a typical week?

**9. Racing and key sessions**
How do I approach race day — conservative and build, or go out at goal pace? Do I tend to go out too hard? For hard training sessions, do I go harder than prescribed or hold back?

**10. Feedback preferences**
What kind of coaching feedback works for me? Direct and blunt, or more considered? Do I want to hear when a session was off-target, or focus on what went well?

**11. Life context**
What does my life look like around training — work demands, travel, sleep patterns, family? A realistic picture of my life helps produce realistic plans.

**12. Fuelling**
What works in training and racing? Any GI issues, things to avoid, protocols that have proven reliable?

**13. Environment**
Where do I live and typically train? What conditions — heat, humidity, hills, terrain? What time of day do I usually train?

**14. Equipment**
What shoes do I rotate? What bike setup? Do I have a power meter and HR monitor?

Once you have everything, generate two files:

---

### File 1: `athlete.json`

Output a JSON object matching this schema exactly. Remove all `_comment` and `_note` fields from the output — they are documentation only. Fill every field with my actual details. Use `null` for anything genuinely unknown.

[paste the contents of context/athlete.template.json here]

---

### File 2: `athlete.md`

Output a rich narrative coaching context document. This is not a summary of the JSON — it is the qualitative, nuanced picture of me as an athlete. Use the template structure below but write in flowing prose under each heading, not bullet points. Be specific and honest based on what I've told you. If I've given you good detail on something, use it. If something is important and I haven't mentioned it, note that it should be added later.

[paste the contents of context/athlete.template.md here]

---

### Instructions for output

- Output File 1 first, as a JSON code block
- Then output File 2, as a markdown code block
- Do not add any explanation or preamble outside the two code blocks
- The JSON must be valid and parseable — no trailing commas, no comments inside the JSON output
- The `last_reviewed` field in athlete.json should be set to today's date
- Pace values in `pace_conventions` and `ride_conventions` should be left as the template defaults unless I have told you I use different zones

Save File 1 as `context/athlete.json` and File 2 as `context/athlete.md` in your JeZR directory.
Then run `jezr profile` to confirm everything loaded correctly.