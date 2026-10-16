// Preferences of the throwaway browser profile harness-browser creates on every start
// (see harness-browser's own comment for why a fresh profile every time). Byte-identical
// to harness/vm/guest/overlay/usr/local/share/harness/firefox-profile/user.js, the copy
// the screenshot harness's own pre-baked test image ships - this file must stay in sync
// with that one, since the goldens this install-verify run is compared against were
// captured against exactly that profile. Each group says what it prevents: anything that
// could open an extra tab, show a prompt or bar, or change the picture between two runs.

// First-run and "what is new" pages, onboarding, default-browser question.
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.startup.homepage_override.buildID", "");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.startup.firstrunSkipsHomepage", true);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.shell.didSkipDefaultBrowserCheckOnFirstRun", true);
user_pref("browser.uitour.enabled", false);
user_pref("browser.messaging-system.whatsNewPanel.enabled", false);
user_pref("browser.discovery.enabled", false);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.toolbars.bookmarks.visibility", "never");
user_pref("extensions.getAddons.showPane", false);
user_pref("extensions.htmlaboutaddons.recommendations.enabled", false);

// Updates: no checks, no restart prompts.
user_pref("app.update.enabled", false);
user_pref("app.update.auto", false);
user_pref("app.update.service.enabled", false);
user_pref("extensions.update.enabled", false);
user_pref("extensions.update.autoUpdateDefault", false);
user_pref("browser.search.update", false);

// Telemetry, studies and every other background connection this profile could make on
// its own (a real install does have network, unlike the test image's guest - these stay
// off regardless, for the same determinism reason, not because the network is absent).
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.ping-centre.telemetry", false);
user_pref("app.normandy.enabled", false);
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("network.captive-portal-service.enabled", false);
user_pref("network.connectivity-service.enabled", false);
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.http.speculative-parallel-limit", 0);
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.safebrowsing.phishing.enabled", false);
user_pref("browser.safebrowsing.downloads.enabled", false);
user_pref("browser.region.update.enabled", false);
user_pref("browser.search.suggest.enabled", false);
user_pref("browser.urlbar.suggest.searches", false);
user_pref("browser.newtabpage.activity-stream.feeds.telemetry", false);
user_pref("browser.newtabpage.activity-stream.telemetry", false);

// Session restore prompts and close warnings.
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.max_resumed_crashes", 0);
user_pref("browser.startup.page", 0);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.warnOnQuit", false);

// Permission prompts and password manager - profile-scoped, unlike the system-wide
// policies.json packages/kuura-firefox/PKGBUILD ships (which this package deliberately
// does not touch, see this package's own PKGBUILD comment): these apply only to
// harness-browser's own throwaway profile, never to a real user's actual Firefox profile.
user_pref("dom.webnotifications.enabled", false);
user_pref("permissions.default.desktop-notification", 2);
user_pref("geo.enabled", false);
user_pref("signon.rememberSignons", false);

// Motion and blinking: nothing may change between two frames by itself.
user_pref("ui.caretBlinkTime", 0);
user_pref("ui.prefersReducedMotion", 1);
user_pref("general.smoothScroll", false);
user_pref("browser.tabs.animate", false);
user_pref("browser.fullscreen.animate", false);
user_pref("toolkit.cosmeticAnimations.enabled", false);
user_pref("browser.download.animateNotifications", false);

// Rendering: forced to the same software-rendering path the goldens were captured with,
// regardless of whether this machine has a real GPU - matching the captured pixels matters
// more here than using whatever hardware happens to be present.
user_pref("gfx.webrender.software", true);
user_pref("layers.acceleration.disabled", true);
user_pref("media.hardware-video-decoding.enabled", false);
