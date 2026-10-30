"""Story names are unique in the picker (was: three identical 'QA Test Reel' entries)."""
import pytest

from opensoul import storyboard as sb


def test_same_title_twice_gets_a_number(tmp_path):
    st = sb.Store(tmp_path)
    a, b, c = (st.create_project("Test Reel") for _ in range(3))
    assert [a.title, b.title, c.title] == ["Test Reel", "Test Reel 2", "Test Reel 3"]
    assert len({a.id, b.id, c.id}) == 3
    assert st.create_project("test reel").title == "test reel 4"  # case-insensitive


def test_rename_onto_another_storys_name_is_refused_but_own_name_is_fine(tmp_path):
    st = sb.Store(tmp_path)
    a, b = st.create_project("One"), st.create_project("Two")
    with pytest.raises(sb.StoryError):
        st.update_project(b.id, title="one")
    assert st.update_project(a.id, title="One").title == "One"
