"use client";

/** Convert wizard state — ONE store, each fact lives exactly once.
 * (v1 kept ten module globals that had to be manually re-synchronized;
 * that entire bug class is retired here.)
 */

import { create } from "zustand";
import { ScanResult, IdentifyResult } from "@/lib/api";
import { Choices } from "@/components/MetadataCompare";

export type WizardStep = "source" | "identify" | "review" | "convert";

interface ConvertState {
  step: WizardStep;
  folder: string;
  scan: ScanResult | null;
  identifyResult: IdentifyResult | null;
  choices: Choices;            // per-field include/value/source decisions
  useProviderTitles: boolean;  // provider track titles vs CUE titles
  artChoiceId: string | null;  // ArtPicker selection ("auto" | "none" | url id)
  jobId: string | null;

  setStep: (s: WizardStep) => void;
  setFolder: (f: string) => void;
  setScan: (s: ScanResult | null) => void;
  setIdentify: (r: IdentifyResult | null) => void;
  setChoices: (c: Choices) => void;
  setUseProviderTitles: (v: boolean) => void;
  setArtChoice: (id: string | null) => void;
  setJobId: (id: string | null) => void;
  reset: () => void;
}

const initial = {
  step: "source" as WizardStep,
  folder: "",
  scan: null,
  identifyResult: null,
  choices: {},
  useProviderTitles: true,
  artChoiceId: "auto",
  jobId: null,
};

export const useConvertStore = create<ConvertState>((set) => ({
  ...initial,
  setStep: (step) => set({ step }),
  setFolder: (folder) => set({ folder }),
  setScan: (scan) => set({ scan }),
  setIdentify: (identifyResult) => set({ identifyResult }),
  setChoices: (choices) => set({ choices }),
  setUseProviderTitles: (useProviderTitles) => set({ useProviderTitles }),
  setArtChoice: (artChoiceId) => set({ artChoiceId }),
  setJobId: (jobId) => set({ jobId }),
  reset: () => set(initial),
}));
