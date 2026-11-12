// Unit tests for the public build's two site settings (lib/site-settings.mjs):
// NEXT_PUBLIC_SITE_URL, the site's address, and NEXT_PUBLIC_GITHUB_URL, its
// GitHub repository. next.config.mjs refuses the public build when either is
// missing or invalid (lib/mode.test.mjs covers that wiring). Also the owner's
// GitHub profile, which githubProfileUrl derives from the repository. Run with
// `npm run test:unit`. Never put this file under e2e/ or e2e-public/:
// Playwright's default test pattern matches *.test.mjs.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { checkGithubUrl, checkSiteUrl, githubProfileUrl, siteSettingsProblems } from "./site-settings.mjs";

const SITE = "NEXT_PUBLIC_SITE_URL";
const GITHUB = "NEXT_PUBLIC_GITHUB_URL";

const SITE_MISSING = `${SITE} is not set: give the site's address, https://<host> with no path and no trailing slash`;
const GITHUB_MISSING = `${GITHUB} is not set: give the repository's address, https://github.com/<owner>/<repo> with nothing after it`;
const notUrl = (value) => `${SITE} is not a URL; got ${JSON.stringify(value)}`;
const notHttps = (value) => `${SITE} must use https; got ${JSON.stringify(value)}`;
const notOrigin = (value) =>
  `${SITE} must be the site's origin alone: https://<host> in lower case, with no path, trailing slash, query, fragment, user name or default port; got ${JSON.stringify(value)}`;
const localhost = (value) => `${SITE} must be the public address, not localhost; got ${JSON.stringify(value)}`;
const ipAddress = (value) => `${SITE} must be a host name, not an IP address; got ${JSON.stringify(value)}`;
const hostName = (value) => `${SITE} must be a public host name, with a dot and no trailing dot; got ${JSON.stringify(value)}`;
const withPort = (port, value) => `${SITE} must have no port; got port ${JSON.stringify(port)} in ${JSON.stringify(value)}`;
const notRepoForm = (value) =>
  `${GITHUB} must be https://github.com/<owner>/<repo> with nothing after it (no trailing slash, path, query or fragment); got ${JSON.stringify(value)}`;
const badOwner = (owner) =>
  `${GITHUB}'s owner must be 1 to 39 letters, digits or hyphens, not starting or ending with a hyphen; got ${JSON.stringify(owner)}`;
const badRepo = (repo) =>
  `${GITHUB}'s repository name must be 1 to 100 letters, digits, ".", "_" or "-", not "." or ".." and not ending in ".git"; got ${JSON.stringify(repo)}`;

// Each value must give exactly [message(value)].
function expectEach(check, values, message) {
  for (const value of values) assert.deepEqual(check(value), [message(value)], JSON.stringify(value));
}

describe("checkSiteUrl: the site's address", () => {
  it("accepts an https origin with a public host name", () => {
    for (const value of [
      "https://omnalynt.example",
      "https://www.example.com",
      "https://sub.example.co.uk",
      "https://xn--bcher-kva.example",
    ]) {
      assert.deepEqual(checkSiteUrl(value), [], value);
    }
  });

  it("refuses a missing value: unset or empty", () => {
    assert.deepEqual(checkSiteUrl(undefined), [SITE_MISSING]);
    assert.deepEqual(checkSiteUrl(""), [SITE_MISSING]);
  });

  it("refuses a value that is not a URL", () => {
    expectEach(checkSiteUrl, ["omnalynt.example", "https://", "https://exa mple.com"], notUrl);
  });

  it("refuses any scheme but https", () => {
    expectEach(checkSiteUrl, ["http://omnalynt.example", "ftp://omnalynt.example"], notHttps);
  });

  it("refuses anything beyond the origin: a path, a trailing slash, a query, a fragment, a user, upper case, the default port, whitespace", () => {
    expectEach(
      checkSiteUrl,
      [
        "https://omnalynt.example/",
        "https://omnalynt.example/path",
        "https://omnalynt.example/?",
        "https://omnalynt.example?q=1",
        "https://omnalynt.example#top",
        "https://user@omnalynt.example",
        "https://user:pw@omnalynt.example",
        "https://Omnalynt.example",
        "HTTPS://omnalynt.example",
        "https://omnalynt.example:443",
        " https://omnalynt.example",
        "https://omnalynt.example\n",
        // A non-ASCII host must be written in its punycode form.
        "https://b\u00fccher.example",
      ],
      notOrigin,
    );
  });

  it("refuses localhost and its subdomains", () => {
    expectEach(checkSiteUrl, ["https://localhost", "https://localhost:3000", "https://app.localhost"], localhost);
  });

  it("refuses an IP address", () => {
    expectEach(
      checkSiteUrl,
      ["https://127.0.0.1", "https://10.0.0.8", "https://0.0.0.0", "https://[::1]", "https://[2001:db8::1]"],
      ipAddress,
    );
  });

  // The default port (:443) is refused above, as beyond the origin.
  it("refuses a port: a deployed address has none", () => {
    assert.deepEqual(checkSiteUrl("https://example.com:8443"), [withPort("8443", "https://example.com:8443")]);
    assert.deepEqual(checkSiteUrl("https://omnalynt.example:80"), [withPort("80", "https://omnalynt.example:80")]);
  });

  it("refuses a host name without a dot or with a trailing dot", () => {
    expectEach(checkSiteUrl, ["https://omnalynt", "https://omnalynt.example."], hostName);
  });
});

describe("checkGithubUrl: the GitHub repository", () => {
  it("accepts https://github.com/<owner>/<repo>", () => {
    for (const value of [
      "https://github.com/e2e-owner/e2e-repo",
      "https://github.com/a/b",
      "https://github.com/Owner-1/repo.name_x",
      `https://github.com/${"a".repeat(39)}/r`,
      `https://github.com/o/${"r".repeat(100)}`,
    ]) {
      assert.deepEqual(checkGithubUrl(value), [], value);
    }
  });

  it("refuses a missing value: unset or empty", () => {
    assert.deepEqual(checkGithubUrl(undefined), [GITHUB_MISSING]);
    assert.deepEqual(checkGithubUrl(""), [GITHUB_MISSING]);
  });

  it("refuses anything that is not exactly https://github.com/<owner>/<repo>", () => {
    expectEach(
      checkGithubUrl,
      [
        "http://github.com/o/r",
        "https://www.github.com/o/r",
        "https://gitlab.com/o/r",
        "https://github.com/o",
        "https://github.com/o/",
        "https://github.com/o/r/",
        "https://github.com/o/r/tree/main",
        "https://github.com/o/r?tab=readme",
        "https://github.com/o/r#readme",
        "https://GitHub.com/o/r",
        "HTTPS://github.com/o/r",
        " https://github.com/o/r",
        "https://github.com//r",
      ],
      notRepoForm,
    );
  });

  it("refuses an owner GitHub would not accept", () => {
    for (const owner of ["-o", "o-", "a".repeat(40), "o_o", "o.o"]) {
      assert.deepEqual(checkGithubUrl(`https://github.com/${owner}/r`), [badOwner(owner)], owner);
    }
  });

  it("refuses a repository name GitHub would not accept, or a clone address", () => {
    for (const repo of [".", "..", "r.git", "r".repeat(101), "r!"]) {
      assert.deepEqual(checkGithubUrl(`https://github.com/o/${repo}`), [badRepo(repo)], repo);
    }
  });
});

describe("githubProfileUrl: the owner's GitHub profile, from the repository's address", () => {
  it("gives the repository's origin plus its owner", () => {
    assert.equal(githubProfileUrl("https://github.com/e2e-owner/e2e-repo"), "https://github.com/e2e-owner");
    assert.equal(githubProfileUrl("https://github.com/a/b"), "https://github.com/a");
    const owner = "a".repeat(39);
    assert.equal(githubProfileUrl(`https://github.com/${owner}/r`), `https://github.com/${owner}`);
  });

  it("keeps the owner as written and drops the repository, even one named like its owner", () => {
    assert.equal(githubProfileUrl("https://github.com/Owner-1/repo.name_x"), "https://github.com/Owner-1");
    assert.equal(githubProfileUrl("https://github.com/same/same"), "https://github.com/same");
  });

  it("is the address's own origin plus one segment, with nothing after it", () => {
    for (const value of ["https://github.com/e2e-owner/e2e-repo", "https://github.com/Owner-1/repo.name_x", `https://github.com/o/${"r".repeat(100)}`]) {
      assert.deepEqual(checkGithubUrl(value), [], value);
      const profile = githubProfileUrl(value);
      assert.equal(typeof profile, "string", value);
      const url = new URL(String(profile));
      assert.equal(url.origin, new URL(value).origin, value);
      assert.equal(url.href, profile, "no trailing slash, query or fragment");
      assert.deepEqual(url.pathname.split("/"), ["", new URL(value).pathname.split("/")[1]], value);
    }
  });

  it("gives nothing for a missing value or one checkGithubUrl refuses", () => {
    for (const value of [
      undefined,
      "",
      "http://github.com/o/r",
      "https://gitlab.com/o/r",
      "https://github.com/o",
      "https://github.com/o/r/",
      "https://github.com/o/r/tree/main",
      " https://github.com/o/r",
      "https://github.com/-o/r",
      "https://github.com/o/r.git",
      "not a url",
    ]) {
      assert.ok(checkGithubUrl(value).length > 0, JSON.stringify(value));
      assert.equal(githubProfileUrl(value), undefined, JSON.stringify(value));
    }
  });
});

describe("siteSettingsProblems: both settings from the environment", () => {
  it("finds no problem when both are valid", () => {
    assert.deepEqual(
      siteSettingsProblems({ [SITE]: "https://omnalynt.example", [GITHUB]: "https://github.com/e2e-owner/e2e-repo" }),
      [],
    );
  });

  it("lists each setting's problem, the site's address first", () => {
    assert.deepEqual(siteSettingsProblems({}), [SITE_MISSING, GITHUB_MISSING]);
    assert.deepEqual(
      siteSettingsProblems({ [GITHUB]: "https://github.com/o/r/", [SITE]: "http://omnalynt.example" }),
      [notHttps("http://omnalynt.example"), notRepoForm("https://github.com/o/r/")],
    );
  });

  it("reports only the setting that is wrong", () => {
    assert.deepEqual(siteSettingsProblems({ [SITE]: "https://omnalynt.example" }), [GITHUB_MISSING]);
    assert.deepEqual(siteSettingsProblems({ [GITHUB]: "https://github.com/o/r" }), [SITE_MISSING]);
  });
});
