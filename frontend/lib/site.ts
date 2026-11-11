import { isSnapshot } from "./mode";

// The public site's name and its two build-time settings: NEXT_PUBLIC_SITE_URL,
// its address, and NEXT_PUBLIC_GITHUB_URL, its GitHub repository.
// next.config.mjs validates both and refuses the public build without them;
// this module never throws. Local mode ignores both (undefined), so its pages
// carry no address of the public site even when a .env file sets them.
export const SITE_NAME = "Omnalynt";

export const SITE_URL: string | undefined = isSnapshot ? process.env.NEXT_PUBLIC_SITE_URL : undefined;

export const GITHUB_URL: string | undefined = isSnapshot ? process.env.NEXT_PUBLIC_GITHUB_URL : undefined;
