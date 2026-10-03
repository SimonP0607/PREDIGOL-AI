export const navGroups = [
  {
    label: "Operations",
    items: [
      { to: "/", label: "Overview", exact: true },
      { to: "/matches", label: "Matches" },
      { to: "/live", label: "Live" },
      { to: "/picks", label: "Picks" },
      { to: "/odds", label: "Odds" },
      { to: "/performance", label: "Performance" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/models", label: "Models" },
      { to: "/backtesting", label: "Backtesting" },
      { to: "/analytics", label: "Analytics" },
    ],
  },
  {
    label: "Football",
    items: [
      { to: "/competitions", label: "Competitions" },
      { to: "/teams", label: "Teams" },
      { to: "/players", label: "Players" },
      { to: "/rankings", label: "Rankings" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/ai-analyst", label: "AI Analyst" },
      { to: "/data-quality", label: "Data Quality" },
      { to: "/admin", label: "System / Admin" },
      { to: "/settings", label: "Settings" },
    ],
  },
] as const;
