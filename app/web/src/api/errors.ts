export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly remaining?: number;
  readonly section?: string;

  constructor(
    message: string,
    status: number,
    code: string,
    extra?: { remaining?: number; section?: string },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    if (extra?.remaining !== undefined) this.remaining = extra.remaining;
    if (extra?.section !== undefined) this.section = extra.section;
  }
}
