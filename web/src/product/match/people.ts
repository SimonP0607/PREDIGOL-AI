/**
 * A man has a page of his own when the provider gave him a name and an id that is one. The provider files the men it could not identify
 * under id 0 (2,402 of the 38,121 matches of the last 400 days have one), and no page belongs to that id: the name is shown and nothing
 * is linked.
 */
export function hasPlayerPage(id: number | null, name: string | null): boolean {
  return id !== null && id > 0 && Boolean(name);
}
