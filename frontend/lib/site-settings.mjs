// The public build's two site settings: NEXT_PUBLIC_SITE_URL, the site's
// address, and NEXT_PUBLIC_GITHUB_URL, its GitHub repository (owner ruling Q3,
// 2026-10-19). Pure checks with no I/O: next.config.mjs runs them in the public
// build and refuses a missing or invalid value; local mode never reads them.
// Each check gives at most one problem, the first that fails. Messages show
// the expected form with placeholders, never an example address.

const SITE = "NEXT_PUBLIC_SITE_URL";
const GITHUB = "NEXT_PUBLIC_GITHUB_URL";

// After URL parsing an IPv4 host is always four dotted numbers.
const IPV4 = /^\d+\.\d+\.\d+\.\d+$/;
// The whole value; no "/", "?" or "#" inside the owner or the repository.
const GITHUB_REPOSITORY = /^https:\/\/github\.com\/([^/?#]+)\/([^/?#]+)$/;
// GitHub's rules: owner 1 to 39 letters, digits or hyphens, with no hyphen at
// either end; repository 1 to 100 letters, digits, ".", "_" or "-".
const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const REPOSITORY = /^[A-Za-z0-9._-]{1,100}$/;

/**
 * The site's address: https://<host>, the origin alone, with a public host
 * name (a dot, no trailing dot, not localhost, not an IP address) and no port.
 * @param {string | undefined} value
 * @returns {string[]}
 */
export function checkSiteUrl(value) {
  if (value === undefined || value === "") {
    return [`${SITE} is not set: give the site's address, https://<host> with no path and no trailing slash`];
  }
  const got = `got ${JSON.stringify(value)}`;
  /** @type {URL} */
  let url;
  try {
    url = new URL(value);
  } catch {
    return [`${SITE} is not a URL; ${got}`];
  }
  if (url.protocol !== "https:") return [`${SITE} must use https; ${got}`];
  // The origin leaves out a path, a query, a fragment, a user name and the
  // default port, and lower-cases the host: any of them makes it differ.
  if (url.origin !== value) {
    return [
      `${SITE} must be the site's origin alone: https://<host> in lower case, with no path, trailing slash, query, fragment, user name or default port; ${got}`,
    ];
  }
  const host = url.hostname;
  if (host === "localhost" || host.endsWith(".localhost")) return [`${SITE} must be the public address, not localhost; ${got}`];
  if (host.startsWith("[") || IPV4.test(host)) return [`${SITE} must be a host name, not an IP address; ${got}`];
  // A deployed address has no port (the default one is refused above).
  if (url.port !== "") return [`${SITE} must have no port; got port ${JSON.stringify(url.port)} in ${JSON.stringify(value)}`];
  if (!host.includes(".") || host.endsWith(".")) return [`${SITE} must be a public host name, with a dot and no trailing dot; ${got}`];
  return [];
}

/**
 * The GitHub repository: exactly https://github.com/<owner>/<repo>, with
 * nothing after it and no clone suffix (".git").
 * @param {string | undefined} value
 * @returns {string[]}
 */
export function checkGithubUrl(value) {
  if (value === undefined || value === "") {
    return [`${GITHUB} is not set: give the repository's address, https://github.com/<owner>/<repo> with nothing after it`];
  }
  const match = GITHUB_REPOSITORY.exec(value);
  if (match === null) {
    return [
      `${GITHUB} must be https://github.com/<owner>/<repo> with nothing after it (no trailing slash, path, query or fragment); got ${JSON.stringify(value)}`,
    ];
  }
  const owner = match[1];
  const repository = match[2];
  if (!OWNER.test(owner)) {
    return [`${GITHUB}'s owner must be 1 to 39 letters, digits or hyphens, not starting or ending with a hyphen; got ${JSON.stringify(owner)}`];
  }
  if (!REPOSITORY.test(repository) || repository === "." || repository === ".." || repository.endsWith(".git")) {
    return [
      `${GITHUB}'s repository name must be 1 to 100 letters, digits, ".", "_" or "-", not "." or ".." and not ending in ".git"; got ${JSON.stringify(repository)}`,
    ];
  }
  return [];
}

/**
 * Both settings' problems, the site's address first.
 * @param {Record<string, string | undefined>} env
 * @returns {string[]}
 */
export function siteSettingsProblems(env) {
  return [...checkSiteUrl(env[SITE]), ...checkGithubUrl(env[GITHUB])];
}
