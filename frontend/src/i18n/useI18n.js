import { useMemo } from 'react';
import { createT } from './translations';

export function useT(langCode) {
  return useMemo(() => createT(langCode || 'en'), [langCode]);
}
