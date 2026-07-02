// src/utils/procurement.ts
import type { Top3RecommendationsResponse } from "../types/procurement";

export function isTop3Output(output: unknown): output is Top3RecommendationsResponse {
  return (
    typeof output === "object" &&
    output !== null &&
    "recommendations" in output &&
    Array.isArray((output as Top3RecommendationsResponse).recommendations)
  );
}