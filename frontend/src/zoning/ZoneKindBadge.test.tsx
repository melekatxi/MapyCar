import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ZoneKindBadge, ZoneKindLegend } from "./ZoneKindBadge";

describe("ZoneKindBadge (2.FE.3)", () => {
  it("distingue urbana y rural por icono, texto y clase, no solo color", () => {
    const { container } = render(
      <>
        <ZoneKindBadge kind="urban" />
        <ZoneKindBadge kind="rural" />
      </>,
    );

    const urban = container.querySelector(".zone-kind--urban");
    const rural = container.querySelector(".zone-kind--rural");
    expect(urban).not.toBeNull();
    expect(rural).not.toBeNull();
    expect(urban).toHaveClass("zone-kind");
    expect(rural).toHaveClass("zone-kind");
    expect(urban?.querySelector("svg")).not.toBeNull();
    expect(rural?.querySelector("svg")).not.toBeNull();
    expect(urban?.querySelector("svg")?.innerHTML).not.toEqual(
      rural?.querySelector("svg")?.innerHTML,
    );
    expect(screen.getByLabelText("Zona urbana")).toHaveTextContent("Urbana");
    expect(screen.getByLabelText("Zona rural")).toHaveTextContent("Rural");
  });

  it("la leyenda expone los tres tipos con iconografía propia", () => {
    render(<ZoneKindLegend />);
    const legend = screen.getByRole("list", { name: "Tipo de zona" });
    expect(legend.querySelector(".zone-kind--urban")).not.toBeNull();
    expect(legend.querySelector(".zone-kind--rural")).not.toBeNull();
    expect(legend.querySelector(".zone-kind--mixed")).not.toBeNull();
    expect(screen.getByLabelText("Zona urbana")).toBeInTheDocument();
    expect(screen.getByLabelText("Zona rural")).toBeInTheDocument();
    expect(screen.getByLabelText("Zona mixta")).toHaveTextContent("Mixta");
  });
});
