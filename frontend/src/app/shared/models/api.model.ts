// Pagination DRF standard
export interface PageResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// Réponse du endpoint /stats/
export interface StatsResponse {
  total: number;
  change: number;
  timeline?: { date: string; count: number }[];
  byType?: { type: string; count: number }[];
}