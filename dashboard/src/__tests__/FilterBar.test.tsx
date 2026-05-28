import { render, screen, fireEvent } from "@testing-library/react";
import { FilterBar } from "@/components/FilterBar";

describe("FilterBar", () => {
  it("toggles label chip and calls onChange", () => {
    const onChange = jest.fn();
    render(<FilterBar onChange={onChange} />);
    const chip = screen.getByRole("button", { name: /政策法规/i });
    fireEvent.click(chip);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ label: "政策法规" }));
  });

  it('shows "全部" and clears filter on click', () => {
    const onChange = jest.fn();
    render(<FilterBar onChange={onChange} />);
    const all = screen.getByRole("button", { name: "全部" });
    fireEvent.click(all);
    expect(onChange).toHaveBeenCalledWith({});
  });
});
