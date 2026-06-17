"use client";

/** Convert wizard state — ONE store, each fact lives exactly once.
 * (v1 kept ten module globals that had to be manually re-synchronized;
 * that entire bug class is retired here.)
 */

import { create } from "zustand";
import { ScanResult, IdentifyResult, ReleaseDetails } from "@/lib/api";
import { Choices } from "@/components/MetadataCompare";

export type WizardStep = "source" | "identify" | "review" | "convert";

interface ConvertState {
  step: WizardStep;
  folder: string;
  scan: ScanResult | null;
  albumGroup: string | null;   // selected parsed_album when folder has multiple albums
  identifyResult: IdentifyResult | null;
  choices: Choices;            // per-field include/value/source decisions
  useProviderTitles: boolean;  // provider track titles vs CUE titles
  artChoiceId: string | null;  // ArtPicker selection ("auto" | "none" | url id)
  // Edition picker: which provider+release the user chose, and its fetched
  // details. null = use the auto-identified release.
  editionId: string | null;    // "provider:id" of the chosen candidate
  editionDetails: ReleaseDetails | null;
  // Per-track title override, keyed "disc-position": true = keep the CUE title
  // instead of the provider/edition title.
  titleExcluded: Record<string, boolean>;
  jobId: string | null;

  setStep: (s: WizardStep) => void;
  setFolder: (f: string) => void;
  setScan: (s: ScanResult | null) => void;
  setAlbumGroup: (g: string | null) => void;
  setIdentify: (r: IdentifyResult | null) => void;
  setChoices: (c: Choices) => void;
  setUseProviderTitles: (v: boolean) => void;
  setArtChoice: (id: string | null) => void;
  setEdition: (id: string | null, details: ReleaseDetails | null) => void;
  setTitleExcluded: (m: Record<string, boolean>) => void;
  setJobId: (id: string | null) => void;
  reset: () => void;
}

const initial = {
  step: "source" as WizardStep,
  folder: "",
  scan: null,
  albumGroup: null,
  identifyResult: null,
  choices: {},
  useProviderTitles: true,
  artChoiceId: "auto",
  editionId: null,
  editionDetails: null,
  titleExcluded: {},
  jobId: null,
};

export const useConvertStore = create<ConvertState>((set) => ({
  ...initial,
  setStep: (step) => set({ step }),
  setFolder: (folder) => set({ folder }),
  setScan: (scan) => set({ scan, albumGroup: null }),
  setAlbumGroup: (albumGroup) => set({ albumGroup }),
  // A fresh identification invalidates any previously chosen edition + overrides.
  setIdentify: (identifyResult) =>
    set({ identifyResult, editionId: null, editionDetails: null, titleExcluded: {} }),
  setChoices: (choices) => set({ choices }),
  setUseProviderTitles: (useProviderTitles) => set({ useProviderTitles }),
  setArtChoice: (artChoiceId) => set({ artChoiceId }),
  setEdition: (editionId, editionDetails) => set({ editionId, editionDetails }),
  setTitleExcluded: (titleExcluded) => set({ titleExcluded }),
  setJobId: (jobId) => set({ jobId }),
  reset: () => set(initial),
}));
