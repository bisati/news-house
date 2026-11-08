(function () {
  "use strict";

  var QUEUE_KEY = "nh.queue";
  var QUEUE_MAX = 500; // oldest entries drop beyond this
  var body = document.body;
  var SEEN_KEY = "nh.seen." + (body.getAttribute("data-edition-id") || "");
  var feedbackUrl = body.getAttribute("data-feedback-url");
  var posts = Array.prototype.slice.call(document.querySelectorAll(".post"));
  var readSent = {};
  var deckReset = {}; // card id -> function that puts its deck back on slide 1
  var seq = 0;

  function each(root, selector, fn) {
    Array.prototype.forEach.call(root.querySelectorAll(selector), fn);
  }

  // ---- Night palette: light by default; the masthead switch turns dark on and off ----
  // (the head script applies ?theme= or the saved choice before first paint)

  var THEME_KEY = "nh.theme";

  function theme() {
    var root = document.documentElement;
    var t = null;
    try { t = new URLSearchParams(window.location.search).get("theme"); } catch (e) { t = null; }
    if (t === "dark" || t === "light") root.setAttribute("data-theme", t);
    var sw = document.querySelector(".theme-toggle");
    if (!sw) return;
    function sync() { sw.setAttribute("aria-checked", root.getAttribute("data-theme") === "dark" ? "true" : "false"); }
    sync();
    sw.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme") !== "dark";
      if (dark) root.setAttribute("data-theme", "dark"); else root.removeAttribute("data-theme");
      try { window.localStorage.setItem(THEME_KEY, dark ? "dark" : "light"); } catch (e) { /* private mode */ }
      sync();
    });
  }

  function cardId(post) {
    return post.getAttribute("data-card-id");
  }

  // ---- Feedback: POST, queue on failure, retry on load --------------------

  function loadQueue() {
    try {
      var q = JSON.parse(window.localStorage.getItem(QUEUE_KEY) || "[]");
      return Array.isArray(q) ? q : [];
    } catch (e) {
      return [];
    }
  }

  function saveQueue(q) {
    try {
      if (q.length) window.localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
      else window.localStorage.removeItem(QUEUE_KEY);
    } catch (e) { /* no storage: no queue */ }
  }

  function enqueue(entry) {
    var q = loadQueue();
    if (!q.some(function (e) { return e.id === entry.id; })) {
      q.push(entry);
      if (q.length > QUEUE_MAX) q = q.slice(q.length - QUEUE_MAX);
      saveQueue(q);
    }
  }

  function dequeue(id) {
    saveQueue(loadQueue().filter(function (e) { return e.id !== id; }));
  }

  function bodyOf(entry) {
    var out = { action: entry.action };
    if (entry.card_id) out.card_id = entry.card_id;
    if (entry.cluster_id) out.cluster_id = entry.cluster_id;
    if (entry.payload !== undefined) out.payload = entry.payload;
    return JSON.stringify(out);
  }

  // A 4xx is permanent (e.g. a card id gone after a rebuild), except 408 and 429.
  function retryable(status) {
    return status < 400 || status >= 500 || status === 408 || status === 429;
  }

  // Resolves "ok" on a 2xx, "drop" on a permanent failure, "retry" on a network
  // error or a retryable status.
  function post(entry) {
    if (!feedbackUrl || !window.fetch) return Promise.resolve("retry");
    return window.fetch(feedbackUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: bodyOf(entry),
      keepalive: true
    }).then(function (r) {
      if (r.ok) return "ok";
      return retryable(r.status) ? "retry" : "drop";
    }, function () { return "retry"; });
  }

  function send(action, ids, payload) {
    seq += 1;
    var entry = { id: Date.now() + "-" + seq, action: action };
    if (ids && ids.card_id) entry.card_id = ids.card_id;
    if (ids && ids.cluster_id) entry.cluster_id = ids.cluster_id;
    if (payload !== undefined) entry.payload = payload;
    return post(entry).then(function (result) {
      if (result === "retry") enqueue(entry);
      return result === "ok";
    });
  }

  function flush() {
    loadQueue().forEach(function (entry) {
      post(entry).then(function (result) {
        if (result !== "retry") dequeue(entry.id);
      });
    });
  }

  // ---- Expand in place -----------------------------------------------------

  function expand(post, open) {
    var more = post.querySelector(".more");
    if (!more) return;
    if (open === undefined) open = more.hidden;
    var id = cardId(post);
    post.classList.toggle("open", open);
    more.hidden = !open;
    var btn = post.querySelector("button.expand");
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    var hc = post.querySelector("button.head-collapse");
    if (hc) hc.hidden = !open;
    if (open && deckReset[id]) deckReset[id]();
    try {
      if (open) history.replaceState(null, "", "#card-" + id);
      else if (location.hash === "#card-" + id) history.replaceState(null, "", location.pathname + location.search);
    } catch (e) { /* history unavailable (e.g. sandboxed frame) */ }
    if (open && !readSent[id]) {
      readSent[id] = true;
      send("read", { card_id: id });
    }
  }

  function wireExpand() {
    posts.forEach(function (post) {
      var btn = post.querySelector("button.expand");
      if (btn) btn.addEventListener("click", function () { expand(post); });
      var headCollapse = post.querySelector("button.head-collapse");
      if (headCollapse) headCollapse.addEventListener("click", function (ev) {
        ev.stopPropagation();
        expand(post, false);
        if (btn) btn.focus();
      });
      var chip = post.querySelector("button.stack-chip");
      if (chip) chip.addEventListener("click", function () { expand(post, true); });
      var collapse = post.querySelector("button.collapse");
      if (collapse) collapse.addEventListener("click", function () { expand(post, false); });
      var head = post.querySelector(".post-head");
      if (head) {
        head.setAttribute("tabindex", "0");
        head.addEventListener("keydown", function (ev) {
          if (ev.target !== head) return;
          if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") {
            ev.preventDefault();
            expand(post);
          }
        });
      }
    });
    var m = /^#card-(.+)$/.exec(location.hash);
    if (m) {
      var wanted;
      try {
        wanted = decodeURIComponent(m[1]);
      } catch (e) {
        wanted = null; // malformed hash: ignore it, keep initialising
      }
      var target = posts.filter(function (p) { return cardId(p) === wanted; })[0];
      if (target) {
        expand(target, true);
        target.scrollIntoView({ block: "start" });
      }
    }
  }

  // ---- Seen: fully in view for 1.5 s ----------------------------------------

  function updateProgress() {
    var n = document.querySelectorAll(".post[data-seen]").length;
    var total = posts.length;
    var state = document.querySelector(".progress-text .progress-state");
    if (state) state.textContent = n + " of " + total + " seen";
    var fill = document.querySelector(".progress-bar .fill");
    if (fill && total) fill.style.transform = "scaleX(" + (n / total).toFixed(4) + ")";
  }

  // Seen card ids per edition, so a reload keeps the progress line and never re-sends.
  function loadSeen() {
    try {
      var s = JSON.parse(window.localStorage.getItem(SEEN_KEY) || "[]");
      return Array.isArray(s) ? s : [];
    } catch (e) {
      return [];
    }
  }

  function saveSeen(id) {
    try {
      var s = loadSeen();
      if (s.indexOf(id) < 0) {
        s.push(id);
        window.localStorage.setItem(SEEN_KEY, JSON.stringify(s));
      }
    } catch (e) { /* no storage: seen lasts for this page only */ }
  }

  function restoreSeen() {
    var ids = loadSeen();
    var n = 0;
    posts.forEach(function (post) {
      if (ids.indexOf(cardId(post)) >= 0) {
        post.setAttribute("data-seen", "");
        n += 1;
      }
    });
    if (n) updateProgress();
  }

  // "Should have been in" taps: the label confirms it, and a reload keeps it.
  var SHOULD_KEY = "nh-should-have";

  function loadShouldHave() {
    try {
      var s = JSON.parse(window.localStorage.getItem(SHOULD_KEY) || "[]");
      return Array.isArray(s) ? s : [];
    } catch (e) {
      return [];
    }
  }

  function saveShouldHave(id) {
    try {
      var s = loadShouldHave();
      if (s.indexOf(id) < 0) {
        s.push(id);
        window.localStorage.setItem(SHOULD_KEY, JSON.stringify(s));
      }
    } catch (e) { /* no storage: noted lasts for this page only */ }
  }

  function markNoted(btn) {
    btn.textContent = "Noted \u2713";
    btn.setAttribute("aria-pressed", "true");
    btn.disabled = true;
  }

  function restoreShouldHave() {
    var ids = loadShouldHave();
    each(document, "button.should-have", function (btn) {
      if (ids.indexOf(btn.getAttribute("data-cluster-id")) >= 0) markNoted(btn);
    });
  }

  function markSeen(post) {
    if (post.hasAttribute("data-seen")) return;
    post.setAttribute("data-seen", "");
    saveSeen(cardId(post));
    send("seen", { card_id: cardId(post) });
    updateProgress();
  }

  function observeSeen() {
    if (!posts.length || !("IntersectionObserver" in window)) return;
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var need = new Map();
    var timers = new Map();
    var thresholds = [0, 1];
    posts.forEach(function (post) {
      var h = post.getBoundingClientRect().height;
      // a post taller than the viewport can never be fully in view
      var r = h > vh && vh > 0 ? Math.floor(100 * vh / h) / 100 : 1;
      need.set(post, r);
      if (thresholds.indexOf(r) < 0) thresholds.push(r);
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var post = en.target;
        var inView = en.isIntersecting && en.intersectionRatio >= need.get(post) - 0.001;
        if (inView && !timers.has(post)) {
          timers.set(post, setTimeout(function () {
            timers.delete(post);
            markSeen(post);
            io.unobserve(post);
          }, 1500));
        } else if (!inView && timers.has(post)) {
          clearTimeout(timers.get(post));
          timers.delete(post);
        }
      });
    }, { threshold: thresholds });
    posts.forEach(function (post) {
      if (!post.hasAttribute("data-seen")) io.observe(post);
    });
  }

  // ---- Reactions -------------------------------------------------------------

  function reactions() {
    each(document, ".react", function (row) {
      var post = row.closest(".post");
      var buttons = row.querySelectorAll("button[data-action]");
      Array.prototype.forEach.call(buttons, function (btn) {
        btn.setAttribute("aria-pressed", "false");
        btn.addEventListener("click", function () {
          Array.prototype.forEach.call(buttons, function (b) {
            var on = b === btn;
            b.classList.toggle("selected", on);
            b.setAttribute("aria-pressed", on ? "true" : "false");
          });
          if (post) send(btn.getAttribute("data-action"), { card_id: cardId(post) });
        });
      });
    });
    each(document, "button.should-have", function (btn) {
      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        send("should_have", { cluster_id: btn.getAttribute("data-cluster-id") });
        markNoted(btn);
        saveShouldHave(btn.getAttribute("data-cluster-id"));
      });
    });
    each(document, "button.also-more", function (btn) {
      btn.addEventListener("click", function () {
        var section = btn.closest(".also");
        if (section) each(section, ".also-list > li[hidden]", function (li) { li.hidden = false; });
        btn.setAttribute("aria-expanded", "true");
        btn.hidden = true;
      });
    });
    each(document, "button.also-fold-toggle", function (btn) {
      btn.addEventListener("click", function () {
        var fold = btn.closest(".also-fold");
        var list = fold && fold.querySelector(".also-folded-list");
        if (!list) return;
        var open = list.hidden;
        list.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
  }

  // ---- Tune tomorrow: one tap per chip, the opposite chip on its topic locks too

  function tune() {
    var chips = [];
    each(document, "button.tune-chip", function (btn) {
      var payload = null;
      try { payload = JSON.parse(btn.getAttribute("data-payload") || "null"); } catch (e) { /* bad markup */ }
      if (payload) chips.push({ btn: btn, payload: payload });
      else btn.disabled = true;
    });
    chips.forEach(function (chip) {
      chip.btn.addEventListener("click", function () {
        var payload = chip.payload;
        if (chip.btn.disabled) return;
        send("tune", null, payload);
        chip.btn.setAttribute("aria-pressed", "true");
        chip.btn.classList.add("selected");
        chip.btn.disabled = true;
        chips.forEach(function (other) {  // "Less X" locks "More X" and back
          if (payload.topic && other.payload.topic === payload.topic) other.btn.disabled = true;
        });
      });
    });
  }

  // ---- Motion (skipped under reduced motion) -------------------------------

  function group(digits, sizes) {
    // sizes: group lengths read from the right of the original, e.g. [3, 3] or [3, 2]
    if (!sizes.length) return digits;
    var out = [];
    var i = digits.length;
    var k = 0;
    while (i > 0) {
      var size = sizes[Math.min(k, sizes.length - 1)];
      out.unshift(digits.slice(Math.max(0, i - size), i));
      i -= size;
      k += 1;
    }
    return out.join(",");
  }

  function countUp(el) {
    var m = /^(\D*)(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?(\D*)$/.exec(el.textContent.trim());
    if (!m) return;
    var parts = m[2].split(",");
    var sizes = parts.length > 1 ? [parts[parts.length - 1].length, parts[parts.length - 2].length] : [];
    var places = m[3] ? m[3].length - 1 : 0;
    var target = parseFloat(m[2].replace(/,/g, "") + (m[3] || ""));
    var final = el.textContent;
    function fmt(v) {
      var s = v.toFixed(places).split(".");
      return m[1] + group(s[0], sizes) + (places ? "." + s[1] : "") + m[4];
    }
    var start = null;
    // the first frame writes the 0, so a page whose frames never run keeps the real figure
    function step(t) {
      if (start === null) start = t;
      var p = Math.min(1, (t - start) / 700);
      el.textContent = p < 1 ? fmt(target * (1 - Math.pow(1 - p, 3))) : final;
      if (p < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  function motion() {
    if (!window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!posts.length || !("IntersectionObserver" in window)) return;
    document.documentElement.classList.add("motion");
    posts.forEach(function (post) {
      var rank = parseInt(post.getAttribute("data-rank"), 10) || 0;
      post.style.setProperty("--i", String(Math.min(Math.max(rank - 1, 0), 6)));
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var post = en.target;
        io.unobserve(post);
        post.classList.add("in");
        each(post, '.visual[data-kind="cover"] .big', countUp);
      });
    }, { threshold: 0 }); // 0, so a post taller than ten viewports still gets "in"
    posts.forEach(function (post) { io.observe(post); });
  }

  function photoFallback() {
    var imgs = document.querySelectorAll("img.photo");
    Array.prototype.forEach.call(imgs, function (img) {
      var cover = img.parentNode.querySelector('[data-kind="cover"]');
      // a source photo has no cover behind it: a broken one takes its whole panel away
      function swap() { if (cover) { img.hidden = true; cover.hidden = false; } else { img.parentNode.hidden = true; } }
      img.addEventListener("error", swap);
      if (img.complete && img.naturalWidth === 0) swap();
    });
  }

  // ---- Slide decks: scroll-snap track, buttons, dots, arrow keys ------------

  function reduced() {
    return !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function decks() {
    posts.forEach(function (post) {
      each(post, ".deck, .stack", function (deck) { carousel(post, deck); });
    });
  }

  // one carousel: a collapsed post's deck, or the strip of other articles in its expanded body
  function carousel(post, deck) {
    var isStack = deck.classList.contains("stack");
    {
      var track = deck.querySelector(".slides");
      if (!track) return;
      var slides = Array.prototype.slice.call(track.querySelectorAll(".slide"));
      var n = slides.length;
      var prev = deck.querySelector("button.slide-prev");
      var next = deck.querySelector("button.slide-next");
      var dots = deck.querySelectorAll(".slide-dots > span");
      var count = deck.querySelector(".slide-count");
      var current = 0;

      function show(i) {
        current = i;
        Array.prototype.forEach.call(dots, function (d, k) { d.classList.toggle("on", k === i); });
        if (count) count.textContent = (i + 1) + " / " + n;
        // a chevron about to hide hands keyboard focus to the other one (or the track) first
        var active = document.activeElement;
        var leaving = (active === prev && i === 0) || (active === next && i === n - 1);
        if (leaving) {
          var other = active === prev ? next : prev;
          if (other && n > 1) {
            other.hidden = false;
            other.focus();
          } else {
            if (!track.hasAttribute("tabindex")) track.setAttribute("tabindex", "-1");
            track.focus();
          }
        }
        if (prev) prev.hidden = i === 0;
        if (next) next.hidden = i === n - 1;
        // chevrons take the current slide's ink through its fill (edition.css, day and night)
        deck.setAttribute("data-fill", slides[i].getAttribute("data-fill"));
      }

      function scrollToSlide(i, instant) {
        var left = slides[i].offsetLeft - slides[0].offsetLeft;
        if (typeof track.scrollTo === "function") {
          try {
            track.scrollTo({ left: left, behavior: instant || reduced() ? "auto" : "smooth" });
            return;
          } catch (e) { /* old engine without the options form */ }
        }
        track.scrollLeft = left;
      }

      function go(i) {
        i = Math.max(0, Math.min(n - 1, i));
        if (i === current || (!isStack && post.classList.contains("open"))) return;
        scrollToSlide(i);
        show(i);
      }

      if (prev) prev.addEventListener("click", function () { go(current - 1); });
      if (next) next.addEventListener("click", function () { go(current + 1); });
      (isStack ? deck : post).addEventListener("keydown", function (ev) {
        if (!isStack && post.classList.contains("open")) return;
        if (ev.altKey || ev.metaKey || ev.ctrlKey) return;
        if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
        ev.preventDefault();
        go(current + (ev.key === "ArrowRight" ? 1 : -1));
      });

      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            if (en.isIntersecting && en.intersectionRatio >= 0.6) show(slides.indexOf(en.target));
          });
        }, { root: track, threshold: 0.6 });
        slides.forEach(function (s) { io.observe(s); });
      } else {
        track.addEventListener("scroll", function () {
          var w = slides[0].offsetWidth || 1;
          show(Math.max(0, Math.min(n - 1, Math.round(track.scrollLeft / w))));
        }, { passive: true });
      }

      var reset = function () {
        scrollToSlide(0, true);
        show(0);
      };
      var before = deckReset[cardId(post)];
      deckReset[cardId(post)] = before ? function () { before(); reset(); } : reset;
      show(0);
    }
  }

  // ---- Live tiles (spec 3.8): refetch every 30 minutes while visible -------

  function liveTiles() {
    var tiles = Array.prototype.slice.call(document.querySelectorAll(".live-tile[data-src]"));
    if (!tiles.length || !window.fetch) return;
    var EVERY = 30 * 60 * 1000;
    var last = Date.now();
    var BANDS = [[0, 50], [51, 100], [101, 200], [201, 300], [301, 400], [401, 500]];
    var PM25 = [[0, 30], [31, 60], [61, 90], [91, 120], [121, 250], [251, 380]];
    var PM10 = [[0, 50], [51, 100], [101, 250], [251, 350], [351, 430], [431, 510]];
    var LABELS = ["Good", "Satisfactory", "Moderate", "Poor", "Very poor", "Severe"];
    var DOTS = ["good", "good", "butter", "tomato", "tomato", "tomato"];

    function sub(c, table) {
      if (typeof c !== "number" || !isFinite(c)) return null;
      c = Math.max(0, c);
      for (var i = 0; i < table.length; i++) {
        if (c <= table[i][1]) {
          return BANDS[i][0] + (BANDS[i][1] - BANDS[i][0]) * (c - table[i][0]) / (table[i][1] - table[i][0]);
        }
      }
      return 500;
    }

    function cpcb(pm25, pm10) {
      var s = [sub(pm25, PM25), sub(pm10, PM10)].filter(function (x) { return x !== null; });
      if (!s.length) return null;
      return Math.min(500, Math.max(0, Math.round(Math.max.apply(null, s))));
    }

    function whenIST(date, now) {
      var parts = {};
      new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric",
        month: "short", hour: "numeric", minute: "2-digit", hourCycle: "h23" })
        .formatToParts(date).forEach(function (p) { parts[p.type] = p.value; });
      var h = parseInt(parts.hour, 10), m = parts.minute;
      var clock = (h % 12 || 12) + (m !== "00" ? ":" + m : "") + (h < 12 ? " am" : " pm");
      var day = date - now < 6 * 24 * 3600 * 1000 ? parts.weekday : parts.weekday + " " + parts.day + " " + parts.month;
      return day + " " + clock;
    }

    function setText(tile, selector, text) {
      var el = tile.querySelector(selector);
      if (el) el.textContent = text;
    }

    // CPCB sub-indices are on 24-hour averages: the mean of the last 24 hourly values up
    // to the current time, nulls ignored; under 12 valid hours, the current value
    function avg24(hourly, key, upto, current) {
      var times = (hourly && hourly.time) || [], values = (hourly && hourly[key]) || [];
      var win = [];
      for (var i = 0; i < times.length && i < values.length; i++) {
        if (!upto || String(times[i]) <= upto) win.push(values[i]);
      }
      var valid = win.slice(-24).filter(function (v) { return typeof v === "number" && isFinite(v); });
      if (valid.length < 12) return current;
      return valid.reduce(function (a, b) { return a + b; }, 0) / valid.length;
    }

    function updateAqi(tile, data) {
      var cur = data && data.current;
      var aqi = cur ? cpcb(avg24(data.hourly, "pm2_5", cur.time, cur.pm2_5),
                           avg24(data.hourly, "pm10", cur.time, cur.pm10)) : null;
      if (aqi === null) return;
      var i = 0;
      while (i < BANDS.length - 1 && aqi > BANDS[i][1]) i++;
      setText(tile, ".aqi-n", String(aqi));
      setText(tile, ".aqi-band", LABELS[i]);
      var band = tile.querySelector(".live-band");
      if (band) band.setAttribute("data-dot", DOTS[i]);
    }

    function updateMatch(tile, data) {
      var id = tile.getAttribute("data-team-id");
      var short = tile.getAttribute("data-short") || "";
      var now = new Date();
      var next = null;
      ((data && data.events) || []).forEach(function (ev) {
        var d = new Date(ev.date);
        if (isNaN(d) || d <= now) return;
        if (!next || d < next.d) next = { d: d, ev: ev };
      });
      if (!next) return;
      var names = {};
      next.ev.competitions[0].competitors.forEach(function (c) {
        var team = c.team || {};
        names[c.homeAway] = String(team.id) === id ? short : (team.displayName || "");
      });
      if (!names.home || !names.away) return;
      setText(tile, ".live-match", names.home + " v " + names.away);
      setText(tile, ".live-when", whenIST(next.d, now));
      var when = tile.querySelector(".live-when");
      if (when) when.setAttribute("data-iso", next.d.toISOString());
      var league = next.ev.league || {};
      if (league.name) setText(tile, ".live-comp", league.name);
    }

    // ---- market tile: Nifty 50 at build or the last market refresh, tap for the trend ----
    function partsIST(d, opts) {
      var p = {};
      new Intl.DateTimeFormat("en-GB", Object.assign({ timeZone: "Asia/Kolkata" }, opts))
        .formatToParts(d).forEach(function (x) { p[x.type] = x.value; });
      return p;
    }

    // "as of 13:39 IST", or "as of Fri 15:30 IST" when the numbers are from an earlier day
    function marketAsOf(tile) {
      var note = tile.querySelector(".mk-asof");
      var d = new Date(tile.getAttribute("data-as-of"));
      if (!note || isNaN(d)) return;
      var day = { year: "numeric", month: "2-digit", day: "2-digit" };
      var t = partsIST(d, { hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short" });
      var same = JSON.stringify(partsIST(d, day)) === JSON.stringify(partsIST(new Date(), day));
      note.textContent = "as of " + (same ? "" : t.weekday + " ") + t.hour + ":" + t.minute + " IST";
      note.hidden = false;
    }

    function wireMarket() {
      var tile = document.querySelector('.live-tile[data-tile="market"]');
      if (!tile) return;
      marketAsOf(tile);  // the tile is a snapshot: say when it is from
      var btn = tile.querySelector(".mk-toggle");
      if (!btn) return;
      btn.addEventListener("click", function () {
        var box = tile.querySelector(".mk-trend");
        var open = btn.getAttribute("aria-expanded") !== "true";
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        box.hidden = !open;
      });
    }
    wireMarket();

    function refresh() {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      last = Date.now();
      tiles.forEach(function (tile) {
        var kind = tile.getAttribute("data-tile");
        var update = kind === "aqi" ? updateAqi : updateMatch;
        fetch(tile.getAttribute("data-src"))
          .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
          .then(function (data) {
            try { update(tile, data); } catch (e) { /* a bad reply leaves the tile as it was */ }
          })
          .catch(function () { /* offline or blocked: the tile keeps its last numbers */ });
      });
    }

    window.setInterval(refresh, EVERY);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible" && Date.now() - last >= EVERY) refresh();
    });
  }

  theme();
  flush();
  restoreSeen();
  decks();
  wireExpand();
  reactions();
  restoreShouldHave();
  tune();
  observeSeen();
  motion();
  photoFallback();
  liveTiles();
})();
