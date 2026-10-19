import CrudPage from '../components/CrudPage';
import { purchase } from '../config/resources';

export default function Purchase() {
  return <CrudPage config={purchase} />;
}
