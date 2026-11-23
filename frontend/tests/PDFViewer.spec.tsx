import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PDFViewer } from '@/components/Elements/PDF';

vi.mock('react-pdf', () => ({
  Document: ({ children }: { children: React.ReactNode }) => children,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {} }
}));

describe('PDFViewer download', () => {
  const clickSpy = vi.fn();
  let createdLinks: HTMLAnchorElement[];

  beforeEach(() => {
    createdLinks = [];
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag, options) => {
      const el = createElement(tag, options);
      if (tag === 'a') {
        (el as HTMLAnchorElement).click = clickSpy;
        createdLinks.push(el as HTMLAnchorElement);
      }
      return el;
    });
    URL.createObjectURL = vi.fn(() => 'blob:pdf');
    URL.revokeObjectURL = vi.fn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(new Blob(['%PDF-1.4'])))
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    clickSpy.mockReset();
  });

  it('downloads cross-origin PDFs as a blob instead of navigating to them', async () => {
    const url = 'https://storage.example.com/threads/1/files/2';
    render(<PDFViewer url={url} name="report.pdf" persistentToolbar />);

    fireEvent.click(screen.getByTitle('Download PDF'));

    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenCalledWith(url);
    expect(createdLinks.at(-1)?.href).toBe('blob:pdf');
    expect(createdLinks.at(-1)?.download).toBe('report.pdf');
  });

  it('leaves same-origin downloads to the native download attribute', () => {
    render(
      <PDFViewer url="/project/file/abc" name="report.pdf" persistentToolbar />
    );

    fireEvent.click(screen.getByTitle('Download PDF'));

    expect(fetch).not.toHaveBeenCalled();
  });
});
