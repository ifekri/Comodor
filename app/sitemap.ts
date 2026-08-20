import type { MetadataRoute } from 'next';
import { site } from '@/lib/site.config';

/*
 * Required by `output: 'export'`. Without it the build refuses these two,
 * because Next cannot know they have no runtime dependencies unless it is
 * told. They are constants, so saying so costs nothing.
 */
export const dynamic = 'force-static';

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      // With the trailing slash, so it is the same URL the canonical names.
      url: `${site.url}/`,
      lastModified: site.updated,
      changeFrequency: 'weekly',
      priority: 1,
    },
  ];
}
