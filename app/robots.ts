import type { MetadataRoute } from 'next';
import { site } from '@/lib/site.config';

/*
 * Required by `output: 'export'`. Without it the build refuses these two,
 * because Next cannot know they have no runtime dependencies unless it is
 * told. They are constants, so saying so costs nothing.
 */
export const dynamic = 'force-static';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: '*', allow: '/' },
    sitemap: `${site.url}/sitemap.xml`,
  };
}
