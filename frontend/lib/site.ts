import { isSnapshot } from "./mode";
import { githubProfileUrl } from "./site-settings.mjs";

// The public site's name and its two build-time settings: NEXT_PUBLIC_SITE_URL,
// its address, and NEXT_PUBLIC_GITHUB_URL, its GitHub repository.
// next.config.mjs validates both and refuses the public build without them;
// this module never throws. Local mode ignores both (undefined), so its pages
// carry no address of the public site even when a .env file sets them.
// Server code only: a client component that imported this module would
// compile the settings into its bundle, so pass a value as a prop instead.
export const SITE_NAME = "Omnalynt";

export const SITE_URL: string | undefined = isSnapshot ? process.env.NEXT_PUBLIC_SITE_URL : undefined;

export const GITHUB_URL: string | undefined = isSnapshot ? process.env.NEXT_PUBLIC_GITHUB_URL : undefined;

// The owner's GitHub profile, for the footer: derived from the repository's
// address, so it is neither a third setting nor an address written in code.
export const GITHUB_PROFILE_URL: string | undefined = isSnapshot
  ? githubProfileUrl(process.env.NEXT_PUBLIC_GITHUB_URL)
  : undefined;
