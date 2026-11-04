// The Agent map's moving parts (ui/agent_map.py): dots that travel along each job's path,
// a narrated feed of what happened, and in "replay" the controls that play the last days back.
(function () {
  const D = JSON.parse(document.getElementById("data").textContent);
  const map = document.getElementById("map");
  const feed = document.getElementById("feed");
  const byId = (id) => document.getElementById(id);
  const IST = { timeZone: "Asia/Kolkata" };
  const time = (ms) =>
    new Date(ms).toLocaleTimeString("en-GB", { ...IST, hour: "2-digit", minute: "2-digit" });
  const day = (ms) =>
    new Date(ms).toLocaleDateString("en-GB", { ...IST, weekday: "short", day: "2-digit", month: "short" });
  const money = (x) => "$" + x.toFixed(x < 0.1 ? 3 : 2);

  // The boxes information passes through, in order, for each kind of job.
  function route(ev) {
    const job = D.jobs[ev.job] || { kind: "rules" };
    const me = "job-" + ev.job;
    switch (job.kind) {
      case "collector":
        return [job.source || "in-exchanges", "tool-download", me, "mem-long"];
      case "ai":
        return ["mem-long", "mem-short", me, "tool-anthropic", me, "mem-long"];
      case "ask":
        return ["in-you", me, "tool-database", me, "tool-anthropic", me, "out-dashboard"];
      case "output":
        return ["mem-long", me, "tool-files", "out-dashboard"];
      default: // the red-flag rules
        return ["mem-long", me, "out-flags"];
    }
  }

  // One line of narration: which layer did what, with what, and where it went.
  function narrate(ev) {
    const job = D.jobs[ev.job] || { name: ev.job, kind: "rules" };
    const result = ev.status === "error" ? "" : ev.summary ? ` Result: ${ev.summary}.` : "";
    let text;
    switch (job.kind) {
      case "collector":
        text = `<b>Perceive</b> · the ${job.name} collector read ${job.from_ || "its source"} and stored what was new in long-term memory.`;
        break;
      case "ai":
        text =
          `<b>Think</b> · the ${job.name} agent took its working set from memory` +
          (ev.calls
            ? `, asked Claude (${job.model}) ${ev.calls} time${ev.calls === 1 ? "" : "s"} for ${money(ev.cost)},`
            : "") +
          " and wrote its answer back to memory.";
        break;
      case "ask":
        text = `<b>Ask</b> · you asked “${ev.summary}”; the agent looked things up in memory (read-only) and answered with Claude.`;
        break;
      case "output":
        text = `<b>Output</b> · the ${job.name} gathered what changed since the last one and saved it for you.`;
        break;
      default:
        text = `<b>Think, by rules</b> · the ${job.name} checked new events, shareholding and deadlines without AI.`;
    }
    if (ev.status === "error") text += ` <span class="bad">It failed: ${ev.error || "see System"}. Observe logged it; the next run catches up.</span>`;
    else if (ev.status === "running") text += " <span class=\"live\">Running now.</span>";
    else if (job.kind !== "ask") text += result;
    const started = ev.job === "ask" ? "" : '<span class="who">the scheduler started it</span>';
    return `<li class="${ev.status}"><time>${day(ev.start)} ${time(ev.start)}</time><span>${text} ${started}</span></li>`;
  }

  function center(id) {
    const el = byId(id);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const m = map.getBoundingClientRect();
    return [r.left - m.left + r.width / 2, r.top - m.top + r.height / 2];
  }

  // A dot travelling through the boxes of a route.
  function send(ids, color, ms) {
    const points = ids.map(center).filter(Boolean);
    if (points.length < 2) return;
    const dot = document.createElement("div");
    dot.className = "packet";
    dot.style.background = color;
    map.appendChild(dot);
    const frames = points.map(([x, y]) => ({ transform: `translate(${x - 6}px, ${y - 6}px)` }));
    dot.animate(frames, { duration: ms, easing: "ease-in-out" }).onfinish = () => dot.remove();
  }

  function flash(id, cls, ms) {
    const el = byId(id);
    if (!el) return;
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), ms);
  }

  function setState(job, state) {
    const el = byId("job-" + job);
    if (!el) return;
    el.classList.remove("ok", "error", "waiting", "running", "off", "idle", "missed");
    el.classList.add(state);
  }

  // In a replay, a box tells what its last replayed run did, not what happened today.
  function describe(ev) {
    const el = byId("job-" + ev.job);
    if (!el || D.mode !== "replay") return;
    let when = el.querySelector(".when");
    if (!when) {
      when = document.createElement("div");
      when.className = "when";
      el.appendChild(when);
    }
    when.textContent =
      `${day(ev.start)} ${time(ev.start)} · ` + (ev.status === "error" ? ev.error : ev.summary);
    let ai = el.querySelector(".ai");
    if (!ai) {
      ai = document.createElement("div");
      ai.className = "ai";
      el.appendChild(ai);
    }
    ai.textContent = ev.calls ? `${ev.calls} AI call${ev.calls === 1 ? "" : "s"} · ${money(ev.cost)}` : "";
  }

  function clearDescriptions() {
    document.querySelectorAll("[data-job]").forEach((el) => {
      const when = el.querySelector(".when");
      if (when) when.textContent = "not run yet in this replay";
      const ai = el.querySelector(".ai");
      if (ai) ai.textContent = "";
    });
  }

  // Show one event on the map: the scheduler starts it, its box lights up, a dot carries
  // the information along its path, and the narration says what happened.
  function play(ev, quiet) {
    if (!quiet) {
      if (ev.job !== "ask") flash("layer-plan", "pulse", 900);
      const box = byId("job-" + ev.job);
      if (box) {
        box.classList.add("running");
        setTimeout(() => setState(ev.job, ev.status === "error" ? "error" : "ok"), 1700);
      }
      const color = ev.status === "error" ? D.colors.down : D.colors.run;
      setTimeout(() => send(route(ev), color, 1600), ev.job === "ask" ? 0 : 300);
      if (ev.calls) setTimeout(() => flash("tool-anthropic", "pulse", 900), 900);
      if (ev.calls) flash("g-0", "pulse", 900); // the budget is checked before every AI call
      if (ev.job === "events") flash("g-3", "pulse", 1200); // the QA checker
      if (ev.status === "error") flash("observe", "alarm", 1400);
    } else {
      setState(ev.job, ev.status === "error" ? "error" : "ok");
    }
    describe(ev);
    feed.insertAdjacentHTML("afterbegin", narrate(ev));
    while (feed.children.length > 60) feed.lastChild.remove();
  }

  if (D.mode === "live") {
    // Today's action: every run so far, newest first; dots loop along the path of each job
    // running now.
    const today = D.events.filter((e) => e.start >= D.today);
    today.forEach((e) => feed.insertAdjacentHTML("afterbegin", narrate(e)));
    if (!today.length) feed.innerHTML = '<li class="none">Nothing has run yet today.</li>';
    const running = D.events.filter((e) => e.status === "running");
    const loop = () =>
      running.forEach((e, i) => setTimeout(() => send(route(e), D.colors.run, 1800), i * 400));
    if (running.length) {
      setTimeout(loop, 600);
      setInterval(loop, 2600);
    }
    return;
  }

  // Replay: play the runs back on the map.
  const all = D.events;
  let from = D.now - 7 * 864e5;
  let span = "week";
  let t = from;
  let i = 0;
  let playing = false;
  let last = performance.now();
  const scrub = byId("scrub");
  const button = byId("play");
  const tally = { runs: 0, errors: 0, calls: 0, cost: 0 };

  function reset(to) {
    // Jump to a time: the boxes show each job's last state before it, the feed its last steps.
    t = to;
    feed.innerHTML = "";
    Object.assign(tally, { runs: 0, errors: 0, calls: 0, cost: 0 });
    Object.keys(D.jobs).forEach((job) => setState(job, "idle"));
    clearDescriptions();
    i = 0;
    while (i < all.length && all[i].start <= t) {
      if (all[i].start >= from) {
        play(all[i], true);
        count(all[i]);
      }
      i++;
    }
    if (!feed.children.length) feed.innerHTML = '<li class="none">Press Play to watch it run.</li>';
    show();
  }

  function count(ev) {
    tally.runs += 1;
    tally.errors += ev.status === "error" ? 1 : 0;
    tally.calls += ev.calls || 0;
    tally.cost += ev.cost || 0;
  }

  function show() {
    byId("clock").textContent = `${day(t)} ${time(t)}`;
    byId("tally").textContent =
      `${tally.runs} runs · ${tally.errors} errors · ${tally.calls} AI calls · ${money(tally.cost)}`;
    scrub.value = Math.round(((t - from) / (D.now - from)) * 1000);
  }

  function tick(now) {
    const dt = Math.min(now - last, 100);
    last = now;
    if (playing) {
      let next = t + dt * Number(byId("speed").value);
      const upcoming = all[i];
      // Skip quiet hours: when nothing happens for a while, jump to just before the next run.
      if (byId("skip").checked && upcoming && upcoming.start - next > 20 * 60e3) {
        next = Math.min(upcoming.start - 60e3, D.now);
      }
      while (i < all.length && all[i].start <= next) {
        if (feed.querySelector(".none")) feed.innerHTML = "";
        play(all[i], false);
        count(all[i]);
        i++;
      }
      t = Math.min(next, D.now);
      if (t >= D.now) {
        playing = false;
        button.textContent = "▶ Play";
      }
      show();
    }
    requestAnimationFrame(tick);
  }

  button.onclick = () => {
    if (t >= D.now) reset(from);
    playing = !playing;
    button.textContent = playing ? "❚❚ Pause" : "▶ Play";
  };
  scrub.oninput = () => reset(from + (scrub.value / 1000) * (D.now - from));
  document.querySelectorAll("[data-span]").forEach((b) => {
    b.onclick = () => {
      span = b.dataset.span;
      document.querySelectorAll("[data-span]").forEach((x) => x.classList.toggle("on", x === b));
      from = span === "today" ? D.today : D.now - 7 * 864e5;
      reset(from);
    };
  });
  reset(from);
  requestAnimationFrame(tick);
})();
