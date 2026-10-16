type LoginPageProps = {
  onLogin: () => void;
  error?: string;
};

export function LoginPage({ onLogin, error }: LoginPageProps) {
  return (
    <>
      <p className="eyebrow">Acesso</p>
      <h1>Entrar</h1>
      <p className="lede">
        Entre com a conta do tribunal para criar minutas de casos fictícios ou de decisões já publicadas.
      </p>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      <button type="button" onClick={onLogin}>
        Entrar
      </button>
    </>
  );
}
